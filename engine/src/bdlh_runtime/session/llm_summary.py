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

_SUMMARY_PROMPT_FILE = "session_history_summary.md"
_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


@dataclass
class SummaryUsage:
    """一次编译周期内摘要调用的用量(编译器据此填 build_* 字段)。"""

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    estimated: bool = False
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
        self._cache_store(system, materials, max_tokens, text)
        return text

    # ── 冻结缓存(生成一次后冻结)───────────────────────────────────────

    def _cache_key(self, system: str, materials: str, max_tokens: int) -> str:
        model = os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL
        payload = json.dumps(
            [self.version, model, self._temperature, system, materials, max_tokens],
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

    def _cache_hit(self, system: str, materials: str, max_tokens: int) -> dict[str, Any] | None:
        if self._cache_path is None:
            return None
        if (os.getenv("LLM_SUMMARY_FREEZE") or "").strip() == "0":
            return None
        entry = self._load_cache().get(self._cache_key(system, materials, max_tokens))
        if isinstance(entry, dict) and entry.get("text"):
            return entry
        return None

    def _cache_store(self, system: str, materials: str, max_tokens: int, text: str) -> None:
        if self._cache_path is None:
            return
        cache = self._load_cache()
        cache[self._cache_key(system, materials, max_tokens)] = {
            "text": text,
            "usage": {
                "model_calls": self._usage.model_calls,
                "input_tokens": self._usage.input_tokens,
                "output_tokens": self._usage.output_tokens,
                "cost": self._usage.cost,
                "duration_ms": self._usage.duration_ms,
                "estimated": self._usage.estimated,
                "warnings": list(self._usage.warnings),
            },
        }
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _replay_usage(self, frozen: dict[str, Any]) -> None:
        usage = dict(frozen.get("usage") or {})
        self._usage.model_calls += int(usage.get("model_calls") or 0)
        self._usage.input_tokens += int(usage.get("input_tokens") or 0)
        self._usage.output_tokens += int(usage.get("output_tokens") or 0)
        self._usage.cost += float(usage.get("cost") or 0.0)
        self._usage.duration_ms += int(usage.get("duration_ms") or 0)
        self._usage.estimated = self._usage.estimated or bool(usage.get("estimated"))
        self._warn("命中冻结摘要缓存(生成一次后冻结,未再次调用模型)")

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
