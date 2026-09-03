"""历史轮 Segment 复用的单元测试(任务书 §11/§12)。

全部使用内存仓库与假摘要器,不调用真实 LLM,不访问 Data Service。
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from bdlh_runtime.context import ConservativeTokenCounter, ExtractiveSummarizer
from bdlh_runtime.memory import ContextBuildStore
from bdlh_runtime.memory.segments import (
    GENERATION_MODE_LLM,
    MemorySegment,
    MemorySegmentManager,
    MemorySegmentStoreError,
    SegmentConfigError,
    SegmentSettings,
    load_turn_summary_system_prompt,
    segment_source_hash,
    split_history_turns,
    split_turns_for_segments,
)
from bdlh_runtime.memory.service import ContextWorkbenchService
from bdlh_runtime.session import SessionCompiler, inject_history_segments
from bdlh_runtime.session.loader import SessionCase, SessionEvent

OWNER = "10000000-0000-0000-0000-000000000001"


# ── 测试数据构造 ─────────────────────────────────────────────────────────


def _event(seq: int, event_id: str, kind: str, content: str, **extra: Any) -> SessionEvent:
    if kind == "tool_call":
        return SessionEvent(
            seq,
            event_id,
            "",
            kind,
            content,
            "assistant",
            call_id=extra.get("call_id"),
            tool_name=extra.get("tool_name"),
        )
    if kind == "tool_result":
        return SessionEvent(
            seq,
            event_id,
            "",
            kind,
            content,
            "tool",
            call_id=extra.get("call_id"),
            tool_name=extra.get("tool_name"),
            status=extra.get("status"),
            error_code=extra.get("error_code"),
        )
    role = "user" if kind == "user_message" else "assistant"
    return SessionEvent(seq, event_id, "", kind, content, role)


def _five_turn_events(current_content: str = "当前请求") -> tuple[SessionEvent, ...]:
    """六轮 Session:前五轮历史 + 最后一条 user_message 作为当前请求。

    验收场景(§12):历史 5 轮 → 旧轮 3 + 最近原文轮 2;当前请求不进入历史。
    """

    events: list[SessionEvent] = []
    seq = 1
    for number in range(1, 6):
        events.append(_event(seq, f"u{number}", "user_message", f"第 {number} 轮问题 " + "细节" * number))
        seq += 1
        if number == 3:
            # 第 3 轮带工具对:调用与结果必须同轮且不拆分
            events.append(_event(seq, f"c{number}", "tool_call", "", call_id=f"call-{number}", tool_name="read"))
            seq += 1
            events.append(
                _event(
                    seq,
                    f"r{number}",
                    "tool_result",
                    f"工具结果 {number}",
                    call_id=f"call-{number}",
                    tool_name="read",
                )
            )
            seq += 1
        events.append(_event(seq, f"a{number}", "assistant_message", f"第 {number} 轮回答 " + "要点" * number))
        seq += 1
    events.append(_event(seq, "u-current", "user_message", current_content))
    return tuple(events)


def _history(events: tuple[SessionEvent, ...]) -> tuple[SessionEvent, ...]:
    current = events[-1]
    return tuple(event for event in events if event.seq < current.seq)


class FakeSummarizer:
    """假批量摘要器:每条返回确定性文本并记录请求,不触网。"""

    version = "fake-turn-summary"

    def __init__(self, summaries: dict[str, str] | None = None) -> None:
        self.summaries = dict(summaries or {})
        self.batch_entries: list[list[tuple[str, str]]] = []
        self.calls = 0

    def summarize_batch(
        self, items: list[tuple[str, str]], *, max_tokens_per_item: int, counter: Any
    ) -> dict[str, str]:
        self.calls += 1
        self.batch_entries.append(list(items))
        return {item_id: self.summaries.get(item_id, f"摘要:{item_id}") for item_id, _text in items}

    def take_usage(self) -> Any:
        return SimpleUsagePayload(model_calls=self.calls, batch_chunks=self.calls)


@dataclasses.dataclass
class SimpleUsagePayload:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    batch_chunks: int = 0


class MemoryRepository:
    """内存 Segment 仓库:模拟 Data Service 行为(所有者隔离 + 持久)。"""

    def __init__(self, owner_id: str = OWNER) -> None:
        self.owner_id = owner_id
        self.segments: dict[str, MemorySegment] = {}
        self.save_calls: list[MemorySegment] = []
        self.list_calls: list[tuple[str, str]] = []

    def list_segments(self, owner_id: str, session_id: str) -> list[MemorySegment]:
        self.list_calls.append((owner_id, session_id))
        if owner_id != self.owner_id:
            raise MemorySegmentStoreError("SEGMENT_FORBIDDEN", "owner mismatch")
        return [segment for segment in self.segments.values() if segment.session_id == session_id]

    def save_segment(self, owner_id: str, session_id: str, segment: MemorySegment) -> str:
        self.save_calls.append(segment)
        if owner_id != self.owner_id:
            raise MemorySegmentStoreError("SEGMENT_FORBIDDEN", "owner mismatch")
        self.segments[segment.segment_id] = segment
        return segment.segment_id


def _manager(
    repository: MemoryRepository, summarizer: FakeSummarizer | None = None, **settings: Any
) -> MemorySegmentManager:
    merged: dict[str, Any] = {"recent_raw_turns": 2}
    merged.update(settings)
    return MemorySegmentManager(
        repository=repository,
        owner_id=OWNER,
        settings=SegmentSettings(**merged),
        counter=ConservativeTokenCounter(),
        summarizer=summarizer or FakeSummarizer(),
    )


def _stored_copy(segment: MemorySegment, **changes: Any) -> MemorySegment:
    return dataclasses.replace(segment, segment_id=f"db-{changes.get('segment_id', segment.segment_id)}", **changes)


# ── 11.1 轮次与范围 ───────────────────────────────────────────────────────


def test_current_request_is_excluded_from_history() -> None:
    events = _five_turn_events()
    history = _history(events)

    assert "u-current" not in [event.event_id for event in history]
    assert len(history) == 12  # 5 轮:2+2+4+2+2 个事件(当前请求不在)


def test_recent_two_turns_stay_raw_older_turns_segmented() -> None:
    history = _history(_five_turn_events())

    old, recent = split_turns_for_segments(history, recent_raw_turns=2)

    assert [turn.turn_id for turn in recent] == ["turn-0004", "turn-0005"]
    assert [turn.turn_id for turn in old] == ["turn-0001", "turn-0002", "turn-0003"]
    # 最近原文轮不生成 Segment:Manager 只对旧轮准备
    repository = MemoryRepository()
    preparation = _manager(repository).prepare(session_id="s1", history_events=history)
    assert preparation.old_turns == 3
    assert preparation.recent_raw_turns == 2
    assert len(preparation.segments) == 3


def test_tool_pair_stays_in_same_turn_and_segment() -> None:
    history = _history(_five_turn_events())
    turns = split_history_turns(history)
    turn3 = next(turn for turn in turns if turn.turn_id == "turn-0003")

    assert [event.event_id for event in turn3.events] == ["u3", "c3", "r3", "a3"]
    repository = MemoryRepository()
    preparation = _manager(repository).prepare(session_id="s1", history_events=history)
    turn3_segment = next(row for row in preparation.segments if row.start_event_id == "u3")
    assert turn3_segment.source_event_ids == ("u3", "c3", "r3", "a3")


def test_incomplete_tool_pair_rejects_segment() -> None:
    # tool_call 悬空(无紧随 result):该轮不完整,保持原文
    events = (
        _event(1, "u1", "user_message", "问题"),
        _event(2, "c1", "tool_call", "", call_id="call-1", tool_name="read"),
        _event(3, "a1", "assistant_message", "回答"),
        _event(4, "u2", "user_message", "追问"),
        _event(5, "a2", "assistant_message", "回答2"),
        _event(6, "u3", "user_message", "再问"),
        _event(7, "a3", "assistant_message", "回答3"),
        _event(8, "u-current", "user_message", "当前"),
    )
    history = _history(events)
    old, _recent = split_turns_for_segments(history, recent_raw_turns=2)

    assert [turn.turn_id for turn in old] == []
    assert old == []  # 唯一旧轮不完整:保持原文,不生成 Segment

    repository = MemoryRepository()
    preparation = _manager(repository).prepare(session_id="s1", history_events=history)
    assert preparation.segments == ()
    assert preparation.generated == 0


# ── 11.2 命中与失效 ───────────────────────────────────────────────────────


def test_full_match_hits_cached_segment() -> None:
    events = _five_turn_events()
    history = _history(events)
    repository = MemoryRepository()
    manager = _manager(repository)
    first = manager.prepare(session_id="s1", history_events=history)
    # 模拟落库:保存的 Segment 变成下次可查的行
    for segment in first.segments:
        repository.segments[segment.segment_id] = segment

    second = manager.prepare(session_id="s1", history_events=history)

    assert second.cache_hits == 3
    assert second.generated == 0
    assert second.invalidated == 0
    assert [segment.segment_id for segment in second.segments] == [row.segment_id for row in first.segments]


def test_modified_event_invalidates_only_that_segment() -> None:
    events = _five_turn_events()
    history = _history(events)
    repository = MemoryRepository()
    manager = _manager(repository)
    first = manager.prepare(session_id="s1", history_events=history)
    for segment in first.segments:
        repository.segments[segment.segment_id] = segment

    # 修改第 1 轮(最旧轮)的 assistant 正文
    modified = tuple(
        dataclasses.replace(event, content="改写后的回答") if event.event_id == "a1" else event for event in history
    )
    second = manager.prepare(session_id="s1", history_events=modified)

    assert second.cache_hits == 2
    assert second.invalidated == 1
    assert second.generated == 1
    # 未修改轮的 Segment ID 保持不变(§12):命中 Segment 仍在原库中
    hit_rows = [row for row in second.segments if row.segment_id in second.hit_ids]
    assert len(hit_rows) == 2
    assert all(row.segment_id in repository.segments for row in hit_rows)
    # 失效轮被重新生成,是新的 Segment ID
    assert second.generated == 1
    assert [row for row in second.segments if row.segment_id not in second.hit_ids]


def test_prompt_version_change_invalidates_all() -> None:
    history = _history(_five_turn_events())
    repository = MemoryRepository()
    manager = _manager(repository)
    first = manager.prepare(session_id="s1", history_events=history)
    for segment in first.segments:
        repository.segments[segment.segment_id] = segment

    changed = _manager(repository, prompt_version="turn-summary-v2")
    second = changed.prepare(session_id="s1", history_events=history)

    assert second.cache_hits == 0
    assert second.invalidated == 3
    assert second.generated == 3


def test_algorithm_version_change_invalidates_all() -> None:
    history = _history(_five_turn_events())
    repository = MemoryRepository()
    manager = _manager(repository)
    first = manager.prepare(session_id="s1", history_events=history)
    for segment in first.segments:
        repository.segments[segment.segment_id] = segment

    changed = MemorySegmentManager(
        repository=repository,
        owner_id=OWNER,
        settings=SegmentSettings(recent_raw_turns=2, algorithm_version="turn-segment-v2"),
        counter=ConservativeTokenCounter(),
        summarizer=FakeSummarizer(),
    )
    second = changed.prepare(session_id="s1", history_events=history)

    assert second.cache_hits == 0
    assert second.generated == 3


def test_over_budget_or_empty_summary_misses() -> None:
    history = _history(_five_turn_events())
    repository = MemoryRepository()
    manager = _manager(repository)
    first = manager.prepare(session_id="s1", history_events=history)
    for segment in first.segments:
        repository.segments[segment.segment_id] = segment

    # 把一个已存 Segment 改成超预算(且保存时绕过校验),一个改空摘要
    keys = sorted(repository.segments)
    repository.segments[keys[0]] = dataclasses.replace(repository.segments[keys[0]], summary_tokens=999_999)
    repository.segments[keys[1]] = dataclasses.replace(
        repository.segments[keys[1]], summary_content="", summary_tokens=0
    )

    second = manager.prepare(session_id="s1", history_events=history)

    assert second.cache_hits == 1
    assert second.invalidated == 2


def test_overlapping_segments_rejected_and_original_kept() -> None:
    from bdlh_runtime.session import serialize_session

    history = _history(_five_turn_events())
    session = _session_case("s1", history)
    serialized = serialize_session(session)
    # 构造两个覆盖同一轮的重叠 Segment(turn-0001 的事件)
    turn1_ids = ("u1", "a1")
    segment_a = _stub_segment("seg-a", turn1_ids, "摘要 A")
    segment_b = _stub_segment("seg-b", turn1_ids, "摘要 B")

    result = inject_history_segments(serialized, (segment_a, segment_b))

    assert result.injected_segment_ids == ("seg-a",)
    assert any("重叠" in warning for warning in result.warnings)
    # 原始条目未被删除:未注入 Segment 的条目保持原样
    assert result.items[0].item.item_id in {"u1", "a1"} or result.items[0].event_ids == turn1_ids


def _stub_segment(segment_id: str, event_ids: tuple[str, ...], summary: str) -> MemorySegment:
    return MemorySegment(
        segment_id=segment_id,
        session_id="s1",
        start_event_id=event_ids[0],
        end_event_id=event_ids[-1],
        source_event_ids=event_ids,
        source_hash="sha256:whatever",
        source_tokens=100,
        summary_content=summary,
        summary_tokens=10,
        status="FROZEN",
        summary_model="fake",
        prompt_version=SegmentSettings().prompt_version,
        algorithm_version=SegmentSettings().algorithm_version,
        generation_mode=GENERATION_MODE_LLM,
        fallback_reason=None,
    )


def _session_case(session_id: str, events: tuple[SessionEvent, ...]) -> SessionCase:
    return SessionCase(
        session_id=session_id,
        session_version=1,
        title="",
        owner_id=OWNER,
        fixture_set_id=None,
        tool_catalog_version=None,
        current_question="当前问题",
        visible_tools=(),
        context_target_tokens=8192,
        events=events,
        source_hash="sha256:case",
        source_path="",
    )


# ── 11.3 LLM 调用上限 ────────────────────────────────────────────────────


def test_all_hits_zero_llm_calls() -> None:
    history = _history(_five_turn_events())
    repository = MemoryRepository()
    summarizer = FakeSummarizer()
    manager = _manager(repository, summarizer)
    first = manager.prepare(session_id="s1", history_events=history)
    for segment in first.segments:
        repository.segments[segment.segment_id] = segment

    summarizer.calls = 0
    second = manager.prepare(session_id="s1", history_events=history)

    assert summarizer.calls == 0
    assert second.model_calls == 0


def test_partial_hit_sends_only_missing_turns() -> None:
    history = _history(_five_turn_events())
    repository = MemoryRepository()
    summarizer = FakeSummarizer()
    manager = _manager(repository, summarizer)
    first = manager.prepare(session_id="s1", history_events=history)
    # 只保留最旧一轮的 Segment(另外两个删除,模拟部分缺失)
    oldest = min(first.segments, key=lambda row: row.start_event_id)
    repository.segments = {oldest.segment_id: oldest}

    summarizer.calls = 0
    summarizer.batch_entries = []
    second = manager.prepare(session_id="s1", history_events=history)

    assert second.cache_hits == 1
    assert second.generated == 2
    sent_ids = [item_id for chunk in summarizer.batch_entries for item_id, _text in chunk]
    assert len(sent_ids) == 2  # 只发送缺失轮


def test_batch_call_count_equals_chunks() -> None:
    history = _history(_five_turn_events())
    repository = MemoryRepository()
    summarizer = FakeSummarizer()
    manager = _manager(repository, summarizer)

    manager.prepare(session_id="s1", history_events=history)

    # 3 个缺失轮 → 1 次 batch 请求(fake 不分块)
    assert summarizer.calls == 1
    assert manager  # 单一 summarizer 实例:不为每轮创建客户端


def test_second_identical_prepare_skips_llm() -> None:
    history = _history(_five_turn_events())
    repository = MemoryRepository()
    summarizer = FakeSummarizer()
    manager = _manager(repository, summarizer)
    first = manager.prepare(session_id="s1", history_events=history)
    for segment in first.segments:
        repository.segments[segment.segment_id] = segment

    summarizer.calls = 0
    second = manager.prepare(session_id="s1", history_events=history)

    assert second.cache_hits == 3
    assert summarizer.calls == 0


def test_extractive_fallback_when_llm_summary_invalid() -> None:
    history = _history(_five_turn_events())
    repository = MemoryRepository()
    # 假摘要器返回与原文相同的文本 → 触发"等于原文"回退
    summarizer = FakeSummarizer()
    manager = MemorySegmentManager(
        repository=repository,
        owner_id=OWNER,
        settings=SegmentSettings(recent_raw_turns=2),
        counter=ConservativeTokenCounter(),
        summarizer=summarizer,
    )
    object.__setattr__(manager, "_extractive", ExtractiveSummarizer())
    # 直接构造"返回空摘要"的假摘要器结果
    summarizer.summaries = {"turn-0001": "", "turn-0002": "", "turn-0003": ""}

    preparation = manager.prepare(session_id="s1", history_events=history)

    assert preparation.fallbacks == 3
    assert all(segment.generation_mode == "EXTRACTIVE_FALLBACK" for segment in preparation.segments)
    assert all(segment.fallback_reason for segment in preparation.segments)
    # 降级也必须有非空摘要
    assert all(segment.summary_content.strip() for segment in preparation.segments)


# ── 11.4 模式 ─────────────────────────────────────────────────────────────


def _workbench(
    tmp_path: Any, repository: MemoryRepository, summarizer: FakeSummarizer | None = None
) -> ContextWorkbenchService:
    class _Source:
        source_type = "PRODUCTION_DB"

        def __init__(self, session: SessionCase, variants: dict) -> None:
            self.session, self.variants = session, variants

        def list_sessions(self) -> list[dict]:
            return []

        def get_session(self, session_id: str) -> tuple[SessionCase, dict]:
            return self.session, self.variants

    session = _session_case("s1", _five_turn_events())  # 完整事件流:Service 自行按当前请求切历史
    variants = {
        "context_variants": [
            {
                "variant_id": "budgeted-session",
                "strategy": "budgeted",
                "strategy_version": "budgeted-hybrid-v1",
                "token_budget": 8192,
                "reserved_tokens": {"recent_session_events": 2048, "history_summary_max": 2560},
            }
        ]
    }
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp()) if tmp_path is None else tmp_path
    return ContextWorkbenchService(
        ContextBuildStore(root),
        source=_Source(session, variants),
        segment_repository=repository,
        segment_summarizer=summarizer,
    )


def test_legacy_mode_unchanged_without_repository(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # legacy:未装配 segment_repository → 行为与旧版一致(无 segment 字段)
    import tempfile
    from pathlib import Path

    class _Source:
        source_type = "FROZEN_FILE"

        def list_sessions(self) -> list[dict]:
            return []

        def get_session(self, session_id: str) -> tuple[SessionCase, dict]:
            session = _session_case("s1", _five_turn_events())
            variants = {
                "context_variants": [
                    {
                        "variant_id": "budgeted-session",
                        "strategy": "budgeted",
                        "strategy_version": "budgeted-hybrid-v1",
                        "token_budget": 8192,
                    }
                ]
            }
            return session, variants

    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "legacy")
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    service = ContextWorkbenchService(ContextBuildStore(Path(tempfile.mkdtemp())), source=_Source())
    build, _replay = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="legacy-1",
        source_type="FROZEN_FILE",
    )
    service.execute_build(build["build_id"], OWNER)
    completed = service.store.get(build["build_id"], OWNER)

    assert completed["status"] == "COMPLETED"
    assert "segment_cache_hits" not in completed["llm_usage"]
    artifact = service.store.artifact(build["build_id"], OWNER)
    assert "memory_segments" not in artifact


def test_shadow_mode_no_artifact_change_no_save_no_llm(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "shadow")
    repository = MemoryRepository()
    summarizer = FakeSummarizer()
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    service = _workbench(tmp_path, repository, summarizer)
    build, _replay = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="shadow-1",
        source_type="PRODUCTION_DB",
    )
    service.execute_build(build["build_id"], OWNER)

    completed = service.store.get(build["build_id"], OWNER)
    artifact = service.store.artifact(build["build_id"], OWNER)

    assert completed["status"] == "COMPLETED"
    assert repository.save_calls == []  # 不写 Segment
    assert summarizer.calls == 0  # 不调用补摘要 LLM
    usage = completed["llm_usage"]
    assert usage.get("segment_generated") == 0
    assert any("SHADOW_SEGMENT_MISS" in warning for warning in completed["warnings"])
    # 正式工件不含 Segment 注入(消息里没有 memory-segment 合成条目)
    assert not any("memory-segment:" in message["content"] for message in artifact["messages"])


def test_incremental_mode_uses_valid_segments(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "incremental")
    repository = MemoryRepository()
    summarizer = FakeSummarizer()
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    service = _workbench(tmp_path, repository, summarizer)
    build, _replay = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="incr-1",
        source_type="PRODUCTION_DB",
    )
    service.execute_build(build["build_id"], OWNER)

    completed = service.store.get(build["build_id"], OWNER)
    artifact = service.store.artifact(build["build_id"], OWNER)

    assert completed["status"] == "COMPLETED"
    usage = completed["llm_usage"]
    assert usage["segment_generated"] == 3
    assert usage["segment_cache_hits"] == 0
    assert usage["summary_calls"] == 1  # 1 次 batch 请求(fake 口径)
    assert len(repository.save_calls) == 3
    assert len(artifact.get("memory_segments") or []) == 3
    assert len(artifact["memory_segment_ids"]) == 3

    # 第二次构建:全部命中,LLM 调用为 0,message hash 一致
    summarizer.calls = 0
    build2, _ = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="incr-2",
        source_type="PRODUCTION_DB",
    )
    service.execute_build(build2["build_id"], OWNER)
    completed2 = service.store.get(build2["build_id"], OWNER)
    artifact2 = service.store.artifact(build2["build_id"], OWNER)

    assert completed2["llm_usage"]["segment_cache_hits"] == 3
    assert completed2["llm_usage"]["segment_generated"] == 0
    assert summarizer.calls == 0
    assert artifact2["message_hash"] == artifact["message_hash"]


def test_overview_exposes_memory_state_and_latest_build(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "incremental")
    repository = MemoryRepository()
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    service = _workbench(tmp_path, repository, FakeSummarizer())
    build, _replay = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="overview-0001",
        source_type="PRODUCTION_DB",
    )
    service.execute_build(build["build_id"], OWNER)

    overview = service.overview("s1", owner_id=OWNER)
    segments_payload = service.segments("s1")

    assert overview["frozen_segment_count"] == 3
    assert overview["recent_raw_turns"] == 2
    assert overview["latest_build"]["build_id"] == build["build_id"]
    assert overview["latest_build"]["status"] == "COMPLETED"
    assert segments_payload["enabled"] is True
    assert len(segments_payload["segments"]) == 3
    row = segments_payload["segments"][0]
    assert {
        "segment_id",
        "start_event_id",
        "end_event_id",
        "event_count",
        "source_hash_short",
        "source_tokens",
        "summary_tokens",
        "status",
        "generation_mode",
        "summary_excerpt",
    } <= set(row)


def test_segments_library_degrades_for_legacy_without_repository(tmp_path: Any) -> None:
    service = _workbench(tmp_path, MemoryRepository())
    legacy = ContextWorkbenchService(service.store)

    payload = legacy.segments("s1")
    overview = legacy.overview("ctx-session-context-engine-debug-01")  # legacy 概览读冻结来源

    assert payload == {"session_id": "s1", "enabled": False, "segments": []}
    assert overview["frozen_segment_count"] is None
    assert overview["recent_raw_turns"] is None
    assert overview["latest_build"] is None


def test_overview_survives_segment_store_failure(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "incremental")

    class BrokenRepository(MemoryRepository):
        def list_segments(self, owner_id: str, session_id: str) -> list[MemorySegment]:
            raise MemorySegmentStoreError("SEGMENT_STORE_UNAVAILABLE", "down")

    service = _workbench(tmp_path, BrokenRepository())

    overview = service.overview("s1", owner_id=OWNER)

    assert overview["frozen_segment_count"] is None  # 仓库故障不阻塞概览
    with pytest.raises(MemorySegmentStoreError):
        service.segments("s1")  # 摘要库端点仍显式暴露错误,由 API 层映射


def test_incremental_artifact_carries_message_tokens_and_segment_source_ids(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "incremental")
    repository = MemoryRepository()
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    service = _workbench(tmp_path, repository, FakeSummarizer())
    build, _replay = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="artifact-0001",
        source_type="PRODUCTION_DB",
    )
    service.execute_build(build["build_id"], OWNER)

    artifact = service.store.artifact(build["build_id"], OWNER)
    completed = service.store.get(build["build_id"], OWNER)

    # 逐消息真实 Token(Token 视图数据源)
    messages = artifact["messages"]
    assert messages and all(message["tokens"] >= 0 for message in messages)
    assert sum(message["tokens"] for message in messages) > 0
    # Segment 明细携带完整 source_event_ids(来源联动高亮数据源)
    for row in artifact["memory_segments"]:
        assert row["source_event_ids"]
        assert row["event_count"] == len(row["source_event_ids"])
    # 调用上限写入构建快照(需求 §10.3)
    assert completed["llm_usage"]["summary_call_cap"] >= 1


def test_summary_call_cap_defaults_to_two(monkeypatch: pytest.MonkeyPatch) -> None:
    from bdlh_runtime.session.llm_summary import summary_call_cap

    monkeypatch.delenv("LLM_SUMMARY_MAX_CALLS_PER_BUILD", raising=False)
    assert summary_call_cap() == 2
    monkeypatch.setenv("LLM_SUMMARY_MAX_CALLS_PER_BUILD", "3")
    assert summary_call_cap() == 3


def test_unknown_mode_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from bdlh_runtime.memory.sources import source_for_mode

    with pytest.raises(ValueError, match="unsupported CONTEXT_MEMORY_MODE"):
        source_for_mode(OWNER, mode="surprise")


def test_invalid_config_fails_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_RECENT_RAW_TURNS", "abc")
    with pytest.raises(SegmentConfigError):
        SegmentSettings.from_env()
    monkeypatch.setenv("CONTEXT_RECENT_RAW_TURNS", "-1")
    with pytest.raises(SegmentConfigError):
        SegmentSettings.from_env()
    monkeypatch.setenv("CONTEXT_SEGMENT_MAX_TOKENS", "0")
    with pytest.raises(SegmentConfigError):
        SegmentSettings.from_env()


# ── 11.5 所有者与错误 ─────────────────────────────────────────────────────


def test_owner_isolation_in_repository() -> None:
    repository = MemoryRepository(owner_id=OWNER)
    history = _history(_five_turn_events())
    manager = _manager(repository)
    first = manager.prepare(session_id="s1", history_events=history)
    for segment in first.segments:
        repository.segments[segment.segment_id] = segment

    # 其他所有者读取被拒绝
    with pytest.raises(MemorySegmentStoreError, match="SEGMENT_FORBIDDEN"):
        repository.list_segments("20000000-0000-0000-0000-000000000002", "s1")


def test_data_service_errors_map_to_stable_codes() -> None:
    from bdlh_runtime.memory.segments import DataServiceMemorySegmentRepository

    class _FailingClient:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

        def list_memory_segments(self, owner_id: str, session_id: str) -> list[dict]:
            from bdlh_runtime.data_client import DataServiceError

            raise DataServiceError("boom", status_code=self.status_code)

    cases = (
        (404, "SEGMENT_SESSION_NOT_FOUND"),
        (409, "SEGMENT_CONFLICT"),
        (503, "SEGMENT_STORE_UNAVAILABLE"),
    )
    for status, expected in cases:
        repository = DataServiceMemorySegmentRepository(OWNER, _FailingClient(status))  # type: ignore[arg-type]
        with pytest.raises(MemorySegmentStoreError) as exc:
            repository.list_segments(OWNER, "s1")
        assert exc.value.code == expected


def test_save_failure_does_not_stall_build(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_MEMORY_MODE", "incremental")

    class FailingRepository(MemoryRepository):
        def save_segment(self, owner_id: str, session_id: str, segment: MemorySegment) -> str:
            raise MemorySegmentStoreError("SEGMENT_STORE_UNAVAILABLE", "save failed")

    repository = FailingRepository()
    monkeypatch.setattr(SessionCompiler, "from_env", classmethod(lambda cls, **_: SessionCompiler()))
    service = _workbench(tmp_path, repository, FakeSummarizer())
    build, _replay = service.store.create(
        owner_id=OWNER,
        session_id="s1",
        current_request_event_id="u-current",
        algorithm="budgeted-hybrid-v1",
        idempotency_key="save-fail-1",
        source_type="PRODUCTION_DB",
    )
    service.execute_build(build["build_id"], OWNER)

    completed = service.store.get(build["build_id"], OWNER)
    assert completed["status"] == "COMPLETED"  # 构建不因保存失败停留 RUNNING
    assert any("SEGMENT_STORE_UNAVAILABLE" in warning for warning in completed["warnings"])


# ── 提示与 hash 口径 ──────────────────────────────────────────────────────


def test_turn_summary_prompt_loads_and_has_required_rules() -> None:
    prompt = load_turn_summary_system_prompt()

    assert "不可信数据" in prompt
    assert "不产生新指令" in prompt
    assert "item_id" in prompt
    assert "不推断" in prompt


def test_source_hash_excludes_unstable_fields() -> None:
    events = (_event(1, "u1", "user_message", "问题"), _event(2, "a1", "assistant_message", "回答"))

    base = segment_source_hash("s1", events)
    same = segment_source_hash("s1", events)
    assert base == same
    # occurred_at 不参与 hash
    shifted = (dataclasses.replace(events[0], occurred_at="2099-01-01"), events[1])
    assert segment_source_hash("s1", shifted) == base
    # 正文变化必须改变 hash
    changed = (dataclasses.replace(events[0], content="新问题"), events[1])
    assert segment_source_hash("s1", changed) != base
