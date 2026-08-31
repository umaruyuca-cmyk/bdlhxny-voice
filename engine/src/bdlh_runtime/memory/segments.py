"""历史轮冻结 Segment:命中复用、缺失批量生成、失效不覆盖。

职责分离(任务书 §5):
- ``MemorySegmentManager`` 负责轮次划分、source hash、命中/失效判定和批量生成;
- ``MemorySegmentRepository``(及 Data Service 实现)只负责经 DataClient 读写
  和字段规范化,不包含业务判定;
- Compiler 只消费准备好的 Segment(见 ``session/history_segments.py``),
  不直接访问 Data Service。

红线:失效 Segment 只标记不覆盖;本阶段只创建新记录;最近原文轮与当前请求
永远不做生成式摘要。
"""

from __future__ import annotations

import dataclasses
import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from bdlh_runtime.context import ConservativeTokenCounter, ExtractiveSummarizer, TokenCounter
from bdlh_runtime.data_client import DataClient, DataServiceError
from bdlh_runtime.session.loader import SessionCase, SessionEvent, canonical_json_hash
from bdlh_runtime.session.serializer import serialize_session

#: Segment 划分/生成算法版本(命中条件之一;变更即整体失效)
SEGMENT_ALGORITHM_VERSION = "turn-segment-v1"

DEFAULT_RECENT_RAW_TURNS = 2
DEFAULT_SEGMENT_MAX_TOKENS = 512
DEFAULT_SEGMENT_PROMPT_VERSION = "turn-summary-v1"

#: 允许命中的冻结状态(Data Service 查询同样只返回这两种)
HIT_SEGMENT_STATUSES = frozenset({"FROZEN", "VALIDATED"})

#: 生成方式取值必须与数据库 CHECK 约束一致
#: (memory_segment_generation_valid: IN ('LLM', 'EXTRACTIVE_FALLBACK'))
GENERATION_MODE_LLM = "LLM"
GENERATION_MODE_EXTRACTIVE = "EXTRACTIVE_FALLBACK"

TURN_SUMMARY_PROMPT_FILE = "session_turn_summary.md"
_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_LLM_SUMMARY_CACHE = Path(__file__).resolve().parents[3] / "var" / "cache" / "llm-summary.json"


class SegmentConfigError(ValueError):
    """CONTEXT_* Segment 配置非法;构建必须明确失败,不得静默采用任意值。"""


class MemorySegmentStoreError(RuntimeError):
    """Segment 存储访问失败;code 稳定供调用方分支。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def load_turn_summary_system_prompt() -> str:
    """加载轮摘要系统提示;文件缺失直接失败,禁止内联兜底。"""

    path = _PROMPTS_DIR / TURN_SUMMARY_PROMPT_FILE
    if not path.is_file():
        raise FileNotFoundError(f"轮摘要系统提示文件缺失:{path}")
    return path.read_text(encoding="utf-8").strip()


@dataclasses.dataclass(frozen=True)
class SegmentSettings:
    """Segment 相关运行配置(任务书 §4.3);非法值在解析处失败。"""

    recent_raw_turns: int = DEFAULT_RECENT_RAW_TURNS
    max_summary_tokens: int = DEFAULT_SEGMENT_MAX_TOKENS
    prompt_version: str = DEFAULT_SEGMENT_PROMPT_VERSION
    algorithm_version: str = SEGMENT_ALGORITHM_VERSION

    @classmethod
    def from_env(cls) -> SegmentSettings:
        recent_raw = _env_int("CONTEXT_RECENT_RAW_TURNS", DEFAULT_RECENT_RAW_TURNS, minimum=0)
        max_tokens = _env_int("CONTEXT_SEGMENT_MAX_TOKENS", DEFAULT_SEGMENT_MAX_TOKENS, minimum=1)
        prompt_version = (os.getenv("CONTEXT_SEGMENT_PROMPT_VERSION") or "").strip() or DEFAULT_SEGMENT_PROMPT_VERSION
        return cls(
            recent_raw_turns=recent_raw,
            max_summary_tokens=max_tokens,
            prompt_version=prompt_version,
        )


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SegmentConfigError(f"{name}={raw!r} 不是合法整数") from exc
    if value < minimum:
        raise SegmentConfigError(f"{name}={raw!r} 低于最小值 {minimum}")
    return value


@dataclasses.dataclass(frozen=True)
class MemorySegment:
    """一个完整历史轮的冻结摘要(与 Data Service 列全字段对齐)。"""

    segment_id: str
    session_id: str
    start_event_id: str
    end_event_id: str
    source_event_ids: tuple[str, ...]
    source_hash: str
    source_tokens: int
    summary_content: str
    summary_tokens: int
    status: str
    summary_model: str | None
    prompt_version: str
    algorithm_version: str
    generation_mode: str
    fallback_reason: str | None


@dataclasses.dataclass(frozen=True)
class SegmentPreparation:
    """一次构建的 Segment 准备结果(注入 Compiler 与页面展示的唯一口径)。"""

    segments: tuple[MemorySegment, ...] = ()
    cache_hits: int = 0
    generated: int = 0
    invalidated: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    batch_chunks: int = 0
    fallbacks: int = 0
    saved_tokens: int = 0
    old_turns: int = 0
    recent_raw_turns: int = 0
    hit_ids: frozenset[str] = frozenset()
    generated_ids: frozenset[str] = frozenset()
    warnings: tuple[str, ...] = ()
    shadow: bool = False
    shadow_misses: int = 0


@dataclasses.dataclass(frozen=True)
class HistoryTurn:
    """按 §4.1 口径划分的完整对话轮;不完整轮不可生成 Segment。"""

    turn_id: str
    events: tuple[SessionEvent, ...]
    complete: bool


def split_history_turns(events: tuple[SessionEvent, ...]) -> list[HistoryTurn]:
    """把历史事件划分为轮:一条 user_message 开启一轮(与 turns.py 口径一致)。"""

    turns: list[HistoryTurn] = []
    current: list[SessionEvent] = []
    number = 0
    started = False
    for event in events:
        if event.type == "user_message" and started:
            turns.append(_finish_turn(f"turn-{number:04d}", tuple(current)))
            current = []
            number += 1
        if event.type == "user_message" and not started:
            started = True
            number = 1
        current.append(event)
    if current:
        turns.append(_finish_turn(f"turn-{number:04d}" if started else "turn-0000", tuple(current)))
    return turns


def _finish_turn(turn_id: str, events: tuple[SessionEvent, ...]) -> HistoryTurn:
    complete = bool(events) and events[0].type == "user_message" and _tool_pairs_intact(events)
    return HistoryTurn(turn_id=turn_id, events=events, complete=complete)


def _tool_pairs_intact(events: tuple[SessionEvent, ...]) -> bool:
    """tool_call 必须紧跟其 tool_result;不完整对的轮不可生成 Segment。"""

    index = 0
    while index < len(events):
        if events[index].type == "tool_call":
            result = events[index + 1] if index + 1 < len(events) else None
            if result is None or result.type != "tool_result":
                return False
            index += 2
            continue
        index += 1
    return True


def split_turns_for_segments(
    events: tuple[SessionEvent, ...],
    recent_raw_turns: int,
) -> tuple[list[HistoryTurn], list[HistoryTurn]]:
    """返回 (旧完整轮, 最近原文轮);不完整轮永远保持原文。"""

    turns = split_history_turns(events)
    complete = [turn for turn in turns if turn.complete]
    keep = min(max(recent_raw_turns, 0), len(complete))
    old = complete[: len(complete) - keep] if keep else list(complete)
    recent = complete[len(complete) - keep :] if keep else []
    return old, recent


def segment_source_hash(session_id: str, events: tuple[SessionEvent, ...]) -> str:
    """Segment source hash 口径(§4.5):只含稳定事件字段,不含时间/行 ID。"""

    return canonical_json_hash(
        {
            "session_id": session_id,
            "source_event_ids": [event.event_id for event in events],
            "events": [
                {
                    "seq": event.seq,
                    "event_id": event.event_id,
                    "type": event.type,
                    "role": event.role,
                    "content": event.content,
                    "call_id": event.call_id,
                    "tool_name": event.tool_name,
                    "arguments": event.arguments,
                    "status": event.status,
                    "error_code": event.error_code,
                }
                for event in events
            ],
        }
    )


def render_turn_source(session_id: str, events: tuple[SessionEvent, ...]) -> str:
    """轮原文的确定性渲染:复用 serializer 的消息/工具对口径。"""

    case = SessionCase(
        session_id=session_id,
        session_version=1,
        title="",
        owner_id=None,
        fixture_set_id=None,
        tool_catalog_version=None,
        current_question="",
        visible_tools=(),
        context_target_tokens=0,
        events=events,
        source_hash="",
        source_path="",
    )
    return "\n\n".join(entry.item.content for entry in serialize_session(case))


class MemorySegmentRepository(Protocol):
    """Segment 读写的最小契约;所有者隔离由实现保证。"""

    def list_segments(self, owner_id: str, session_id: str) -> list[MemorySegment]: ...

    def save_segment(self, owner_id: str, session_id: str, segment: MemorySegment) -> str: ...


class DataServiceMemorySegmentRepository:
    """经 Data Service 读写 Segment;字段规范化与错误映射都在这里。"""

    def __init__(self, owner_id: str, client: DataClient | None = None) -> None:
        if not owner_id:
            raise ValueError("owner_id is required for memory segment repository")
        self.owner_id = owner_id
        self.client = client or DataClient()

    def list_segments(self, owner_id: str, session_id: str) -> list[MemorySegment]:
        self._check_owner(owner_id)
        try:
            rows = self.client.list_memory_segments(owner_id, session_id)
        except DataServiceError as exc:
            raise self._map_error(exc) from exc
        segments: list[MemorySegment] = []
        for row in rows:
            try:
                segments.append(_segment_from_payload(row, session_id))
            except (KeyError, TypeError, ValueError) as exc:
                raise MemorySegmentStoreError("SEGMENT_PAYLOAD_INVALID", str(exc)) from exc
        return segments

    def save_segment(self, owner_id: str, session_id: str, segment: MemorySegment) -> str:
        self._check_owner(owner_id)
        try:
            return self.client.save_memory_segment(
                session_id,
                {
                    "accountId": owner_id,
                    "startEventId": segment.start_event_id,
                    "endEventId": segment.end_event_id,
                    "sourceEventIds": list(segment.source_event_ids),
                    "sourceHash": segment.source_hash,
                    "sourceTokens": segment.source_tokens,
                    "summaryContent": segment.summary_content,
                    "summaryTokens": segment.summary_tokens,
                    "status": segment.status,
                    "summaryModel": segment.summary_model,
                    "promptVersion": segment.prompt_version,
                    "algorithmVersion": segment.algorithm_version,
                    "generationMode": segment.generation_mode,
                    "fallbackReason": segment.fallback_reason,
                },
            )
        except DataServiceError as exc:
            raise self._map_error(exc) from exc

    def _check_owner(self, owner_id: str) -> None:
        if owner_id != self.owner_id:
            raise MemorySegmentStoreError("SEGMENT_FORBIDDEN", f"segment store bound to owner {self.owner_id!r}")

    @staticmethod
    def _map_error(exc: DataServiceError) -> MemorySegmentStoreError:
        if exc.status_code == 404:
            return MemorySegmentStoreError("SEGMENT_SESSION_NOT_FOUND", str(exc))
        if exc.status_code == 409:
            return MemorySegmentStoreError("SEGMENT_CONFLICT", str(exc))
        return MemorySegmentStoreError("SEGMENT_STORE_UNAVAILABLE", str(exc))


def _segment_from_payload(row: dict[str, Any], session_id: str) -> MemorySegment:
    """Data Service 行 → MemorySegment;兼容 camelCase 新契约与旧 snake_case 行。"""

    def field(*names: str) -> Any:
        for name in names:
            if name in row:
                return row[name]
        raise KeyError(f"memory segment row missing {names[0]}")

    def optional(*names: str) -> Any:
        for name in names:
            if name in row:
                return row[name]
        return None

    # Data Service 行映射不携带 sessionId(查询本身已按会话过滤),缺省回落到请求参数
    raw_session = row.get("sessionId", row.get("session_id"))
    return MemorySegment(
        segment_id=str(field("segmentId", "segment_id", "id")),
        session_id=str(raw_session or session_id),
        start_event_id=str(field("startEventId", "start_event_id")),
        end_event_id=str(field("endEventId", "end_event_id")),
        source_event_ids=_event_ids(field("sourceEventIds", "source_event_ids")),
        source_hash=str(field("sourceHash", "source_hash")),
        source_tokens=int(field("sourceTokens", "source_tokens") or 0),
        summary_content=str(field("summaryContent", "summary_content") or ""),
        summary_tokens=int(field("summaryTokens", "summary_tokens") or 0),
        status=str(field("status") or ""),
        summary_model=_optional_str(optional("summaryModel", "summary_model")),
        prompt_version=str(field("promptVersion", "prompt_version") or ""),
        algorithm_version=str(field("algorithmVersion", "algorithm_version") or ""),
        generation_mode=str(field("generationMode", "generation_mode") or ""),
        fallback_reason=_optional_str(optional("fallbackReason", "fallback_reason")),
    )


def _event_ids(value: Any) -> tuple[str, ...]:
    """source_event_ids 可能是 JSON 数组、JSON 字符串或 PGobject 风格 dict。"""

    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        value = value.get("value")
        if isinstance(value, str):
            value = json.loads(value)
    if not isinstance(value, list):
        raise TypeError(f"source_event_ids has unsupported shape {type(value)!r}")
    return tuple(str(item) for item in value)


def _optional_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


class MemorySegmentManager:
    """轮次 → hash → 命中 → 批量生成 → 冻结保存 的编排器。"""

    def __init__(
        self,
        *,
        repository: MemorySegmentRepository,
        owner_id: str,
        settings: SegmentSettings | None = None,
        counter: TokenCounter | None = None,
        summarizer: Any | None = None,
        summarizer_factory: Callable[[], Any] | None = None,
        extractive: ExtractiveSummarizer | None = None,
    ) -> None:
        self.repository = repository
        self.owner_id = owner_id
        self.settings = settings or SegmentSettings.from_env()
        self._counter = counter or ConservativeTokenCounter()
        self._summarizer = summarizer
        self._summarizer_factory = summarizer_factory or _default_summarizer_factory
        self._extractive = extractive or ExtractiveSummarizer()

    def prepare(
        self,
        *,
        session_id: str,
        history_events: tuple[SessionEvent, ...],
        allow_generation: bool = True,
        allow_save: bool = True,
    ) -> SegmentPreparation:
        warnings: list[str] = []
        old_turns, recent_turns = split_turns_for_segments(history_events, self.settings.recent_raw_turns)
        stored = self._list_stored(session_id, warnings)
        by_event_ids = {segment.source_event_ids: segment for segment in stored}

        prepared: dict[str, MemorySegment] = {}
        hit_ids: set[str] = set()
        invalidated = 0
        missing: list[tuple[HistoryTurn, str]] = []
        for turn in old_turns:
            ids = tuple(event.event_id for event in turn.events)
            candidate = by_event_ids.get(ids)
            source_hash = segment_source_hash(session_id, turn.events)
            if candidate is not None and self._is_hit(candidate, source_hash):
                prepared[turn.turn_id] = candidate
                hit_ids.add(candidate.segment_id)
                continue
            if candidate is not None:
                invalidated += 1
                warnings.append(
                    f"segment {candidate.segment_id} 与当前轮不匹配(hash/版本/预算校验未过),"
                    "按失效处理并重新生成,不修改旧记录"
                )
            missing.append((turn, source_hash))

        usage = SimpleUsage()
        fallbacks = 0
        generated_ids: set[str] = set()
        if missing and allow_generation:
            generated, usage, fallbacks = self._generate(session_id, missing, warnings)
            for turn_id, segment in generated.items():
                prepared[turn_id] = segment
                generated_ids.add(segment.segment_id)
        elif missing:
            warnings.append(
                f"SHADOW_SEGMENT_MISS: {len(missing)} 个旧轮缺少可用 Segment,当前模式不调用 LLM 补齐"
            )

        segments = tuple(prepared[turn.turn_id] for turn in old_turns if turn.turn_id in prepared)
        saved_tokens = sum(max(0, segment.source_tokens - segment.summary_tokens) for segment in segments)
        return SegmentPreparation(
            segments=segments,
            cache_hits=len(hit_ids),
            generated=len(generated_ids),
            invalidated=invalidated,
            model_calls=usage.model_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            batch_chunks=usage.batch_chunks,
            fallbacks=fallbacks,
            saved_tokens=saved_tokens,
            old_turns=len(old_turns),
            recent_raw_turns=len(recent_turns),
            hit_ids=frozenset(hit_ids),
            generated_ids=frozenset(generated_ids),
            warnings=tuple(warnings),
            shadow=not allow_generation,
            shadow_misses=len(missing) if not allow_generation else 0,
        )

    def _list_stored(self, session_id: str, warnings: list[str]) -> list[MemorySegment]:
        try:
            return self.repository.list_segments(self.owner_id, session_id)
        except MemorySegmentStoreError as exc:
            warnings.append(f"{exc.code}: 读取历史 Segment 失败,本次按无可用 Segment 处理({exc.message})")
            return []

    def _is_hit(self, segment: MemorySegment, source_hash: str) -> bool:
        """命中条件(§4.4)必须全部满足;不满足只失效,不覆盖。

        所有者/Session 隔离由 Repository 查询条件保证(list 只返回当前
        account+session 的行),这里不再重复判定。
        """

        return (
            segment.status in HIT_SEGMENT_STATUSES
            and bool(segment.source_event_ids)
            and segment.source_hash == source_hash
            and segment.algorithm_version == self.settings.algorithm_version
            and segment.prompt_version == self.settings.prompt_version
            and segment.summary_content.strip() != ""
            and 0 < segment.summary_tokens <= self.settings.max_summary_tokens
        )

    def _generate(
        self,
        session_id: str,
        missing: list[tuple[HistoryTurn, str]],
        warnings: list[str],
    ) -> tuple[dict[str, MemorySegment], SimpleUsage, int]:
        settings = self.settings
        turns = [turn for turn, _hash in missing]
        sources = {turn.turn_id: render_turn_source(session_id, turn.events) for turn in turns}
        entries = [(turn.turn_id, sources[turn.turn_id]) for turn in turns]
        summarizer = self._ensure_summarizer()
        mapping = summarizer.summarize_batch(
            entries,
            max_tokens_per_item=settings.max_summary_tokens,
            counter=self._counter,
        )
        usage = _take_usage(summarizer)

        requested_ids = {turn.turn_id for turn in turns}
        extra = sorted(set(mapping) - requested_ids)
        if extra:
            warnings.append(f"批量轮摘要返回了请求外的 item_id,已忽略:{extra[:5]}")

        generated: dict[str, MemorySegment] = {}
        fallbacks = 0
        for turn, expected_hash in missing:
            source_text = sources[turn.turn_id]
            summary = str(mapping.get(turn.turn_id) or "").strip()
            mode = GENERATION_MODE_LLM
            reason: str | None = None
            extractive_text = self._extractive.summarize([source_text], settings.max_summary_tokens, self._counter)
            if not summary or summary == source_text or self._counter.count(summary) > settings.max_summary_tokens:
                summary = extractive_text
                mode = GENERATION_MODE_EXTRACTIVE
                reason = "LLM 摘要缺失、等于原文或超出 Segment 预算"
            elif summary == extractive_text:
                # LLMSummarizer 内部失败时回退抽取式;结果与确定性抽取式一致即如实标注
                mode = GENERATION_MODE_EXTRACTIVE
                reason = "LLM 调用失败或响应无效,摘要器已回退抽取式"
            if not summary.strip():
                warnings.append(f"轮 {turn.turn_id} 摘要仍为空,拒绝保存并跳过该 Segment")
                continue
            if mode == GENERATION_MODE_EXTRACTIVE:
                fallbacks += 1
            segment = self._freeze(
                session_id,
                turn,
                expected_hash=expected_hash,
                source_text=source_text,
                summary=summary,
                generation_mode=mode,
                fallback_reason=reason,
                warnings=warnings,
            )
            if segment is not None:
                generated[turn.turn_id] = segment
        return generated, usage, fallbacks

    def _freeze(
        self,
        session_id: str,
        turn: HistoryTurn,
        *,
        expected_hash: str,
        source_text: str,
        summary: str,
        generation_mode: str,
        fallback_reason: str | None,
        warnings: list[str],
    ) -> MemorySegment | None:
        events = turn.events
        source_hash = segment_source_hash(session_id, events)
        # 写入前再次核对 source hash(§7.3):与命中判定时的口径必须一致
        if source_hash != expected_hash:
            warnings.append(f"轮 {turn.turn_id} source hash 在写入前发生变化,放弃保存")
            return None
        segment = MemorySegment(
            segment_id=f"local-{uuid.uuid4()}",
            session_id=session_id,
            start_event_id=events[0].event_id,
            end_event_id=events[-1].event_id,
            source_event_ids=tuple(event.event_id for event in events),
            source_hash=source_hash,
            source_tokens=self._counter.count(source_text),
            summary_content=summary,
            summary_tokens=self._counter.count(summary),
            status="FROZEN",
            summary_model=self._summary_model(),
            prompt_version=self.settings.prompt_version,
            algorithm_version=self.settings.algorithm_version,
            generation_mode=generation_mode,
            fallback_reason=fallback_reason,
        )
        try:
            segment_id = self.repository.save_segment(self.owner_id, session_id, segment)
        except MemorySegmentStoreError as exc:
            warnings.append(f"{exc.code}: 保存 Segment 失败,本次构建继续使用内存副本({exc.message})")
            return segment
        return dataclasses.replace(segment, segment_id=segment_id)

    def _summary_model(self) -> str | None:
        model = (os.getenv("LLM_MODEL") or "").strip()
        return model or None

    def _ensure_summarizer(self) -> Any:
        if self._summarizer is None:
            self._summarizer = self._summarizer_factory()
        return self._summarizer


@dataclasses.dataclass
class SimpleUsage:
    """summarizer 未提供 take_usage 时的零用量兜底。"""

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    batch_chunks: int = 0


def _take_usage(summarizer: Any) -> Any:
    take = getattr(summarizer, "take_usage", None)
    if not callable(take):
        return SimpleUsage()
    usage = take()
    if usage is None:
        return SimpleUsage()
    return usage


def _default_summarizer_factory() -> Any:
    from bdlh_runtime.session.llm_summary import LLMSummarizer

    return LLMSummarizer(system_prompt=load_turn_summary_system_prompt(), cache_path=_LLM_SUMMARY_CACHE)
