"""single-summary 策略的一次性 LLM 摘要基准(接真实模型,可注入 fake 单测)。

隔离红线:
- 输入只能是序列化后的 Session 事件文本(构建器 render 后的条目),
  不读取 gold 任何内容,不复用 budgeted 策略的选择结果;
- 系统提示从 ``engine/prompts/session_history_summary.md`` 加载,禁止内联长字符串,
  提示词中不得出现预期答案。

冻结纪律(variants.json ``summary_generate_once_and_freeze``):供应商在
temperature=0 下仍可能非确定,因此启用缓存(``cache_path``)时同一输入只生成
一次,之后命中缓存返回冻结文本并回放当时的用量——重复编译的
compiled_context_hash 一致;``LLM_SUMMARY_FREEZE=0`` 关闭缓存强制重新生成。

失败降级链(降级事件记入 ``take_usage().warnings``,由编译器写入工件 warnings):
1. LLM 调用异常/超时/返回空 → 直接回退 ``ExtractiveSummarizer`` 对原文摘要;
2. 返回超过 max_tokens → 对 LLM 输出按句边界收缩;仍超 → 回退抽取式对原文摘要。

成本记录:input/output tokens 优先取响应 usage_metadata /
response_metadata.token_usage,取不到时按 counter 估算并标记 estimated=true;
cost = tokens × 单价(环境变量 LLM_PRICE_INPUT_PER_MTOK /
LLM_PRICE_OUTPUT_PER_MTOK,每百万 Token 价格;未配置时 cost=0 并注明)。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bdlh_runtime.context import ConservativeTokenCounter, ExtractiveSummarizer, TokenCounter
from bdlh_runtime.infra.llm import DEFAULT_LLM_MODEL, create_llm

LLM_SUMMARY_VERSION = "llm-single-summary-v1"

#: 缓存结构版本 v2:v1 条目把摘要器累计用量当自身用量保存并在命中时回放,
#: 造成缓存命中被计入本轮调用/费用(三角累加放大)。v2 只保存该次生成请求
#: 自身的增量用量(generation_usage),命中缓存不再计入本轮任何费用。
LLM_SUMMARY_CACHE_VERSION = "llm-summary-cache-v2"

_SUMMARY_PROMPT_FILE = "session_history_summary.md"
_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


@dataclass
class SummaryUsage:
    """一次编译周期内摘要调用的用量(编译器据此填 build_* 字段)。

    计量口径(缓存修复后):
    - ``model_calls``/``input_tokens``/``output_tokens``/``cost``/``duration_ms``
      只统计**本轮真实发送到模型服务**的请求;缓存命中不计入;
    - ``cache_hits`` 是本轮命中冻结缓存的次数;
    - ``logical_calls`` 是逻辑摘要操作数(含缓存命中),仅供核对。
    """

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    estimated: bool = False
    cache_hits: int = 0
    logical_calls: int = 0
    #: 用量口径标识:摘要构建固定 COMPRESSION,与 Agent 主模型(AGENT)分开统计
    purpose: str = "COMPRESSION"
    #: 批量分块摘要的 chunk 数(P0-1;single 路径为 0)
    batch_chunks: int = 0
    warnings: list[str] = field(default_factory=list)


def load_summary_system_prompt() -> str:
    """加载摘要系统提示;文件缺失直接失败,禁止内联兜底。"""

    path = _PROMPTS_DIR / _SUMMARY_PROMPT_FILE
    if not path.is_file():
        raise FileNotFoundError(f"摘要系统提示文件缺失:{path}")
    return path.read_text(encoding="utf-8").strip()


def _leading_sentences(text: str, max_tokens: int, counter: TokenCounter) -> str:
    """按完整句子从头填充;单句超预算时跳过该句,不截断半句。"""

    taken: list[str] = []
    used = 0
    for sentence in _SENTENCE_SPLIT.split(text):
        if not sentence.strip():
            continue
        tokens = counter.count(sentence)
        if used + tokens > max_tokens:
            if not taken and tokens > max_tokens:
                continue
            break
        taken.append(sentence)
        used += tokens
    return "".join(taken).strip()


def _parse_summary_items(content: str) -> dict[str, str] | None:
    """解析 chunk 响应为 item_id → summary;失败或出现重复 id 返回 None。

    重复 item_id 视为无效响应(字典推导会静默去重,必须显式检测)。
    """

    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except ValueError:
        return None
    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    mapping: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id") or "").strip()
        summary = row.get("summary")
        if item_id and isinstance(summary, str):
            if item_id in mapping:
                return None  # 重复 id:整份响应无效
            mapping[item_id] = summary
    return mapping


class LLMSummarizer:
    """满足 ``HistorySummarizer`` 协议的一次性 LLM 摘要器(temperature 固定 0)。

    ``cache_path`` 非空时启用「生成一次后冻结」:同一 (提示词, 材料, 预算,
    模型) 组合只调用一次模型,之后命中缓存返回冻结文本并回放当时的用量。
    """

    version = LLM_SUMMARY_VERSION

    def __init__(
        self,
        llm: Any | None = None,
        *,
        temperature: float = 0.0,
        timeout_s: float | None = None,
        counter: TokenCounter | None = None,
        system_prompt: str | None = None,
        cache_path: str | Path | None = None,
    ) -> None:
        self._llm = llm
        self._llm_resolved = llm is not None
        self._temperature = temperature
        self._timeout_s = timeout_s if timeout_s is not None else float(os.getenv("LLM_SUMMARY_TIMEOUT_S", "120"))
        self._counter = counter or ConservativeTokenCounter()
        self._system_prompt = system_prompt
        self._cache_path = Path(cache_path) if cache_path else None
        self._usage = SummaryUsage()
        self._extractive = ExtractiveSummarizer()

    # ── HistorySummarizer 协议 ─────────────────────────────────────────────

    def summarize(self, texts: Sequence[str], max_tokens: int, counter: TokenCounter) -> str:
        usable = [text.strip() for text in texts if text and text.strip()]
        if not usable or max_tokens <= 0:
            return ""

        self._usage.logical_calls += 1
        system = self._system_prompt if self._system_prompt is not None else load_summary_system_prompt()
        materials = "\n\n".join(
            f"[材料 {index}]\n{text}" for index, text in enumerate(usable, start=1)
        )
        frozen = self._cache_hit(system, materials, max_tokens)
        if frozen is not None:
            self._replay_usage(frozen)
            return frozen["text"]

        llm = self._ensure_llm()
        if llm is None:
            self._warn("LLM 不可用(未配置 LLM_API_KEY/LLM_BASE_URL 或客户端创建失败),回退抽取式摘要")
            return self._extractive.summarize(usable, max_tokens, counter)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"材料如下,请在 {max_tokens} token 以内输出历史摘要:\n\n{materials}"},
        ]
        started = time.perf_counter()
        before = self._usage_snapshot()
        try:
            # temperature=0 + seed=0 冻结口径;不支持 seed 的实现退回普通调用
            try:
                response = llm.invoke(messages, seed=0)
            except TypeError:
                response = llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001 —— 调用异常一律降级,不中断编译
            self._warn(f"LLM 摘要调用失败({type(exc).__name__}: {exc}),回退抽取式摘要")
            return self._extractive.summarize(usable, max_tokens, counter)
        duration_ms = round((time.perf_counter() - started) * 1000)

        content = self._response_text(response)
        self._record_usage(response, system, materials, content, duration_ms)
        if not content.strip():
            self._warn("LLM 摘要返回空内容,回退抽取式摘要")
            return self._extractive.summarize(usable, max_tokens, counter)

        header = f"[history-summary method={self.version} items={len(usable)}]"
        budget = max_tokens - counter.count(header)
        if budget <= 0:
            self._warn("摘要预算不足以容纳输出头,回退抽取式摘要")
            return self._extractive.summarize(usable, max_tokens, counter)
        if counter.count(content) > budget:
            shrunk = _leading_sentences(content, budget, counter)
            if shrunk and counter.count(shrunk) <= budget:
                self._warn("LLM 摘要超出预算,已按句边界收缩")
                content = shrunk
            else:
                self._warn("LLM 摘要无法按句收缩至预算,回退抽取式对原文摘要")
                return self._extractive.summarize(usable, max_tokens, counter)
        text = f"{header}\n{content}"
        self._cache_store(system, materials, max_tokens, text, before=before)
        return text

    # ── 批量分块摘要(P0-1:一次 Session 的摘要请求数有硬上限)──────────

    #: 生成式压缩的调用上限与分块预算(env 可覆盖;默认 4 次请求/构建)
    MAX_CALLS_PER_BUILD_DEFAULT = 4
    MAX_INPUT_TOKENS_PER_CALL_DEFAULT = 24_000

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = (os.getenv(name) or "").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return default

    def summarize_batch(
        self,
        items: Sequence[tuple[str, str]],
        *,
        max_tokens_per_item: int,
        counter: TokenCounter,
    ) -> dict[str, str]:
        """有限分块摘要:候选条目 → 少量 chunk → 每 chunk 一次结构化 LLM 请求。

        纪律(修复方案 §5):
        - 单次构建的摘要请求数 ≤ ``LLM_SUMMARY_MAX_CALLS_PER_BUILD``(默认 4);
        - chunk 按 ``LLM_SUMMARY_MAX_INPUT_TOKENS_PER_CALL`` 切分;
        - 响应为 ``{"items":[{"item_id","summary"}]}`` JSON:不接受请求外的
          item_id,重复 id 视为整 chunk 无效;缺失项用抽取式补足,不为单项再调 LLM;
        - JSON 解析失败 → 整 chunk 回退抽取式,不做修复循环;
        - 超出调用上限的剩余条目直接回退抽取式并写入 warnings;
        - 每条摘要仍走冻结缓存(kind=batch-item),命中不计本轮费用。
        """
        results: dict[str, str] = {}
        pending: list[tuple[str, str]] = []
        system = self._system_prompt if self._system_prompt is not None else load_summary_system_prompt()
        for item_id, text in items:
            stripped = (text or "").strip()
            if not stripped or max_tokens_per_item <= 0:
                continue
            self._usage.logical_calls += 1
            frozen = self._cache_hit(system, stripped, max_tokens_per_item, kind="batch-item")
            if frozen is not None:
                self._replay_usage(frozen)
                results[item_id] = str(frozen["text"])
            else:
                pending.append((item_id, stripped))
        if not pending:
            return results

        llm = self._ensure_llm()
        if llm is None:
            self._warn("LLM 不可用(未配置 LLM_API_KEY/LLM_BASE_URL),批量摘要整体回退抽取式")
            for item_id, text in pending:
                results[item_id] = self._extractive.summarize([text], max_tokens_per_item, counter)
            return results

        max_calls = self._env_int("LLM_SUMMARY_MAX_CALLS_PER_BUILD", self.MAX_CALLS_PER_BUILD_DEFAULT)
        input_budget = max(
            self._env_int("LLM_SUMMARY_MAX_INPUT_TOKENS_PER_CALL", self.MAX_INPUT_TOKENS_PER_CALL_DEFAULT)
            - counter.count(system),
            1024,
        )
        chunks: list[list[tuple[str, str]]] = []
        current: list[tuple[str, str]] = []
        used = 0
        for row in pending:
            tokens = counter.count(row[1]) + 16  # 条目包裹开销
            if current and used + tokens > input_budget:
                chunks.append(current)
                current, used = [], 0
            current.append(row)
            used += tokens
        if current:
            chunks.append(current)

        overflow: list[tuple[str, str]] = []
        if len(chunks) > max_calls:
            overflow = [row for chunk in chunks[max_calls:] for row in chunk]
            chunks = chunks[:max_calls]
            self._warn(
                f"摘要分块数({len(chunks) + len(overflow)} 预计)超过调用上限({max_calls}),"
                f"剩余 {len(overflow)} 条回退抽取式压缩"
            )
        self._usage.batch_chunks += len(chunks)

        for chunk in chunks:
            self._summarize_chunk(llm, system, chunk, max_tokens_per_item, counter, results)

        for item_id, text in overflow:
            results[item_id] = self._extractive.summarize([text], max_tokens_per_item, counter)
        return results

    def _summarize_chunk(
        self,
        llm: Any,
        system: str,
        chunk: list[tuple[str, str]],
        max_tokens_per_item: int,
        counter: TokenCounter,
        results: dict[str, str],
    ) -> None:
        """一次 chunk 请求 + 校验;任何失败整体回退抽取式,不重试不修复。"""
        requested_ids = [item_id for item_id, _ in chunk]
        body = "\n\n".join(f"[item id={item_id}]\n{text}" for item_id, text in chunk)
        user_content = (
            f"请对下列 {len(chunk)} 个条目逐条生成摘要,每条不超过 {max_tokens_per_item} token,"
            '严格返回 JSON:{{"items":[{{"item_id":"...","summary":"..."}}]}},不要输出 JSON 以外的内容。\n\n'
            f"{body}"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        started = time.perf_counter()
        try:
            try:
                response = llm.invoke(messages, seed=0)
            except TypeError:
                response = llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001 —— chunk 失败整体降级
            self._warn(f"批量摘要 chunk 调用失败({type(exc).__name__}: {exc}),该 chunk 回退抽取式")
            for item_id, text in chunk:
                results[item_id] = self._extractive.summarize([text], max_tokens_per_item, counter)
            return
        duration_ms = round((time.perf_counter() - started) * 1000)
        content = self._response_text(response)
        self._record_usage(response, system, user_content, content, duration_ms)

        mapping = _parse_summary_items(content)
        invalid_reason = ""
        if mapping is None:
            invalid_reason = "JSON 解析失败或存在重复 item_id"
        if invalid_reason:
            self._warn(f"批量摘要响应无效({invalid_reason}),该 chunk 回退抽取式,不进入修复循环")
            for item_id, text in chunk:
                results[item_id] = self._extractive.summarize([text], max_tokens_per_item, counter)
            return

        requested = set(requested_ids)
        for item_id, text in chunk:
            summary = mapping.get(item_id, "")
            summary = (summary or "").strip()
            if not summary or summary == text or counter.count(summary) > max_tokens_per_item:
                shrunk = _leading_sentences(summary, max_tokens_per_item, counter) if summary else ""
                if shrunk and counter.count(shrunk) <= max_tokens_per_item and shrunk != text:
                    summary = shrunk
                else:
                    if summary:
                        self._warn(f"条目 {item_id} 的 LLM 摘要缺失或超预算,回退抽取式")
                    summary = self._extractive.summarize([text], max_tokens_per_item, counter)
            results[item_id] = summary
            self._cache_store(
                system, text, max_tokens_per_item, summary, kind="batch-item", generation_usage={}
            )
        unknown = [item_id for item_id in mapping or {} if item_id not in requested]
        if unknown:
            self._warn(f"批量摘要响应包含请求外的 item_id,已忽略:{unknown[:5]}")

    # ── 冻结缓存(生成一次后冻结)───────────────────────────────────────

    def _cache_key(self, system: str, materials: str, max_tokens: int, *, kind: str = "single") -> str:
        model = os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL
        payload = json.dumps(
            [self.version, kind, model, self._temperature, system, materials, max_tokens],
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if self._cache_path is None or not self._cache_path.is_file():
            return {}
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _cache_hit(self, system: str, materials: str, max_tokens: int, *, kind: str = "single") -> dict[str, Any] | None:
        if self._cache_path is None:
            return None
        if (os.getenv("LLM_SUMMARY_FREEZE") or "").strip() == "0":
            return None
        entry = self._load_cache().get(self._cache_key(system, materials, max_tokens, kind=kind))
        if isinstance(entry, dict) and entry.get("text"):
            return entry
        return None

    def _cache_store(
        self,
        system: str,
        materials: str,
        max_tokens: int,
        text: str,
        *,
        kind: str = "single",
        before: dict[str, Any] | None = None,
        generation_usage: dict[str, Any] | None = None,
    ) -> None:
        """写入 v2 缓存条目:只存该条摘要生成请求自身的增量用量。

        ``generation_usage`` 显式给出时使用(batch 分块条目);否则由
        ``before`` 快照与当前累计用量之差计算(single 路径)。
        v1 旧文件首次改写前备份为 ``*.v1.backup.json``,旧条目正文保留,
        其用量字段标记 untrusted_legacy_usage,不再进入任何统计。
        """
        if self._cache_path is None:
            return
        cache = self._load_cache()
        if generation_usage is None:
            generation_usage = self._usage_delta(before or self._usage_snapshot())
        cache[self._cache_key(system, materials, max_tokens, kind=kind)] = {
            "version": 2,
            "text": text,
            "generation_usage": generation_usage,
        }
        legacy = [key for key, entry in cache.items() if isinstance(entry, dict) and entry.get("version") != 2]
        if legacy and not (self._cache_path.parent / (self._cache_path.name + ".v1.backup.json")).is_file():
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            (self._cache_path.parent / (self._cache_path.name + ".v1.backup.json")).write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        for key in legacy:
            entry = cache[key]
            entry.setdefault("text", "")
            entry["untrusted_legacy_usage"] = True
            entry.pop("usage", None)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _replay_usage(self, frozen: dict[str, Any]) -> None:
        """缓存命中:不计入本轮模型调用/Token/费用,只计 cache_hits。

        v1 条目没有可信的历史用量(generation_usage 缺失),不回放;
        v2 的 generation_usage 属于历史生成请求,不进入本轮统计。
        """
        self._usage.cache_hits += 1
        self._warn("命中冻结摘要缓存(生成一次后冻结,未再次调用模型,不计入本轮调用与费用)")

    # ── 用量快照/增量 ─────────────────────────────────────────────────────

    def _usage_snapshot(self) -> dict[str, Any]:
        u = self._usage
        return {
            "model_calls": u.model_calls,
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cost": u.cost,
            "duration_ms": u.duration_ms,
            "estimated": u.estimated,
        }

    def _usage_delta(self, before: dict[str, Any]) -> dict[str, Any]:
        after = self._usage_snapshot()
        return {
            key: after[key] - before[key] if isinstance(after[key], (int, float)) else after[key]
            for key in after
        }

    # ── 用量记录 ──────────────────────────────────────────────────────────

    def take_usage(self) -> SummaryUsage:
        """返回并清零本编译周期的用量(编译器在编译前后各调用一次)。"""

        usage = self._usage
        self._usage = SummaryUsage()
        return usage

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _ensure_llm(self) -> Any | None:
        if self._llm_resolved:
            return self._llm
        self._llm = create_llm(
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL"),
            model=os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL,
            temperature=self._temperature,
            timeout=self._timeout_s,
            # 摘要失败有抽取式降级兜底;SDK 默认重试 2 次会把一次超时放大成
            # 3 倍墙钟时间,大 Session 下表现为任务长时间无进展并占住批次槽
            max_retries=0,
        )
        self._llm_resolved = True
        return self._llm

    def _warn(self, message: str) -> None:
        self._usage.warnings.append(message)

    @staticmethod
    def _response_text(response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, Sequence):
            parts = []
            for part in content:
                text = getattr(part, "text", None)
                parts.append(text if isinstance(text, str) else str(part))
            return "".join(parts).strip()
        return str(content).strip()

    def _record_usage(
        self, response: Any, system: str, materials: str, output: str, duration_ms: int
    ) -> None:
        input_tokens: int | None = None
        output_tokens: int | None = None
        usage_meta = getattr(response, "usage_metadata", None) or {}
        if isinstance(usage_meta, dict) and usage_meta.get("input_tokens") is not None:
            input_tokens = int(usage_meta["input_tokens"])
            output_tokens = int(usage_meta.get("output_tokens") or 0)
        else:
            token_usage = (getattr(response, "response_metadata", None) or {}).get("token_usage")
            if isinstance(token_usage, dict):
                input_tokens = int(token_usage.get("prompt_tokens") or 0) or None
                output_tokens = int(token_usage.get("completion_tokens") or 0)
        estimated = input_tokens is None
        if input_tokens is None:
            # usage 元数据缺失:按计数口径估算并标记
            input_tokens = self._counter.count(system) + self._counter.count(materials)
            output_tokens = self._counter.count(output)
            self._warn("LLM 响应缺少 usage 元数据,token 用量为估算值(estimated=true)")

        price_input = os.environ.get("LLM_PRICE_INPUT_PER_MTOK")
        price_output = os.environ.get("LLM_PRICE_OUTPUT_PER_MTOK")
        if price_input and price_output:
            cost = (
                input_tokens * float(price_input) / 1_000_000
                + (output_tokens or 0) * float(price_output) / 1_000_000
            )
        else:
            cost = 0.0
            self._warn("未配置 LLM_PRICE_INPUT_PER_MTOK/LLM_PRICE_OUTPUT_PER_MTOK 单价,cost=0")

        self._usage.model_calls += 1
        self._usage.input_tokens += input_tokens
        self._usage.output_tokens += output_tokens or 0
        self._usage.cost += cost
        self._usage.duration_ms += duration_ms
        self._usage.estimated = self._usage.estimated or estimated
