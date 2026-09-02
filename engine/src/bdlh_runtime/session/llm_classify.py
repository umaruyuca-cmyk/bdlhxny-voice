"""LLM 辅助上下文分类(需求 §9.1/§10.3/§13.2 步骤 7):语义分类辅助,批量一次。

定位与红线:
- 代码预规则只处理语义上可确定性判定的情况(已被取代 → 干扰过期);
  其余条目属于"语义不明确的候选",由本模块**单次批量调用** LLM 判四分类;
- 每次构建最多 1 次分类调用(``CONTEXT_CLASSIFY_CALL_CAP``,默认 1,§10.3);
- 输出非法/调用失败/超限 → 调用方回退代码默认分类(全部可压缩),
  与既有行为一致,不阻塞构建;真实请求与用量如实计数(失败也算调用);
- 输入只含条目编号、角色与截断正文,不含 gold/评测标注;提示词从
  ``prompts/context_classify.md`` 加载,禁止内联。

隔离口径:分类调用与摘要调用分开计数(classification_* vs summary_*/build_*),
两者都属 COMPRESSION 用途,与 Agent 主模型分开(§11.1)。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bdlh_runtime.context import ConservativeTokenCounter
from bdlh_runtime.infra.llm import DEFAULT_LLM_MODEL, create_llm

CLASSIFY_PROMPT_VERSION = "context-classify-v1"
_CLASSIFY_PROMPT_FILE = "context_classify.md"
_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

_VALID_CATEGORIES = frozenset({"required", "compressible", "reference_only", "distractor"})
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

#: 单条目正文截断长度与总输入预算(字符;分类不需要全文,首尾足够定语义)
_PER_ITEM_CHARS = 600
_TOTAL_CHARS_DEFAULT = 16000


def classify_call_cap() -> int:
    """单次构建的分类辅助调用上限(§10.3:0 或 1;0=关闭分类辅助)。"""

    raw = os.environ.get("CONTEXT_CLASSIFY_CALL_CAP")
    if not raw:
        return 1
    try:
        value = int(raw)
    except ValueError:
        return 1
    return max(0, min(value, 1))


def load_classify_system_prompt() -> str:
    path = _PROMPTS_DIR / _CLASSIFY_PROMPT_FILE
    if not path.is_file():
        raise FileNotFoundError(f"分类提示文件缺失:{path}")
    return path.read_text(encoding="utf-8").strip()


@dataclass
class ClassifyUsage:
    """一次构建周期内分类辅助的用量与结果(调用方写入 llm_usage/快照)。"""

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    #: 判定结果:item_id → (classification_value, reason);失败为空
    decisions: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: 分类统计(含代码预规则与回退,由调用方汇总)
    error_code: str | None = None
    truncated: bool = False


class LLMContextClassifier:
    """经统一 LLM 基建的批量上下文分类器;失败不伪造结论。"""

    def __init__(self, *, llm: Any | None = None, model: str | None = None) -> None:
        self._llm_override = llm
        self._model_override = model
        self._counter = ConservativeTokenCounter()

    def _ensure_llm(self) -> Any | None:
        if self._llm_override is not None:
            return self._llm_override
        if not (os.environ.get("LLM_API_KEY") or "").strip():
            return None
        # 批量分类(逐条给依据)比单条摘要慢;默认 30s 对推理模型太紧
        timeout = float(os.environ.get("CONTEXT_CLASSIFY_TIMEOUT_S") or 180)
        return create_llm(
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL"),
            model=os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL,
            temperature=0,
            timeout=timeout,
            max_retries=0,
        )

    def classify(
        self,
        entries: list[tuple[str, str, str]],
    ) -> ClassifyUsage:
        """批量分类:``entries`` = (item_id, role, content)。

        返回 ``ClassifyUsage``;``decisions`` 为空且 ``error_code`` 非空表示
        本次辅助失败,调用方应回退代码默认分类。
        """

        usage = ClassifyUsage()
        cap = classify_call_cap()
        if cap <= 0:
            usage.error_code = "CLASSIFY_DISABLED"
            return usage
        llm = self._ensure_llm()
        if llm is None:
            usage.error_code = "LLM_UNAVAILABLE"
            return usage

        # 输入预算:单条截断 + 总量截断(截断部分不分类,回退默认)
        total = 0
        budget = int(os.environ.get("CONTEXT_CLASSIFY_MAX_CHARS") or _TOTAL_CHARS_DEFAULT)
        picked: list[tuple[str, str, str]] = []
        truncated = False
        for item_id, role, content in entries:
            text = " ".join(str(content or "").split())
            if len(text) > _PER_ITEM_CHARS:
                text = text[:_PER_ITEM_CHARS] + "…"
            cost = len(text) + 24
            if total + cost > budget:
                truncated = True
                break
            total += cost
            picked.append((item_id, role, text))
        if not picked:
            usage.error_code = "CLASSIFY_INPUT_EMPTY"
            return usage

        lines = [
            f"{index}. [item_id={item_id}][{role}] {text}"
            for index, (item_id, role, text) in enumerate(picked, start=1)
        ]
        prompt = (
            f"{load_classify_system_prompt()}\n\n=== 待分类条目 ===\n" + "\n".join(lines)
            + "\n\n请逐条输出分类 JSON;item_id 必须使用条目方括号里给出的 item_id 原文。"
        )
        started = time.perf_counter()
        try:
            response = llm.invoke([{"role": "user", "content": prompt}])
        except Exception as exc:  # noqa: BLE001 —— 分类失败回退代码默认,不阻塞构建
            usage.model_calls = 1
            usage.duration_ms = round((time.perf_counter() - started) * 1000)
            usage.error_code = _classify_error(exc)
            return usage
        usage.model_calls = 1
        usage.duration_ms = round((time.perf_counter() - started) * 1000)
        meta = getattr(response, "usage_metadata", None)
        if isinstance(meta, dict) and meta.get("input_tokens") is not None:
            usage.input_tokens = int(meta["input_tokens"])
            usage.output_tokens = int(meta.get("output_tokens") or 0)
        else:
            usage.input_tokens = self._counter.count(prompt)
            usage.output_tokens = self._counter.count(str(getattr(response, "content", "")))
        usage.truncated = truncated

        content = getattr(response, "content", response)
        if not isinstance(content, str):
            content = str(content)
        parsed = _parse_items(content)
        if parsed is None:
            usage.error_code = "LLM_INVALID_OUTPUT"
            return usage
        known_ids = {item_id for item_id, _role, _text in picked}
        ordinal_ids = {str(index): item_id for index, (item_id, _role, _text) in enumerate(picked, start=1)}
        for row in parsed:
            item_id = str(row.get("item_id") or "")
            category = str(row.get("classification") or "").strip().lower()
            if item_id not in known_ids:
                # 模型可能回序号:按条目顺序映射回真实 id
                item_id = ordinal_ids.get(item_id, "")
            if not item_id or item_id not in known_ids or category not in _VALID_CATEGORIES:
                continue  # 请求外 id / 非法类别:丢弃,不伪造
            usage.decisions[item_id] = (category, str(row.get("reason") or "")[:200])
        if not usage.decisions:
            usage.error_code = "LLM_INVALID_OUTPUT"
        return usage


def _parse_items(content: str) -> list[dict[str, Any]] | None:
    """解析模型输出:剥离推理块,容忍围栏;从 {"items"} 键起做平衡截取。"""

    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    candidates = [text]
    start = text.find('{"items"')
    if start >= 0:
        candidates.insert(0, text[start : text.rfind("}") + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            match = _JSON_OBJECT.search(candidate)
            if match is None:
                continue
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
            return [row for row in parsed["items"] if isinstance(row, dict)]
    return None


def _classify_error(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return "LLM_TIMEOUT"
    if "rate" in text and "limit" in text:
        return "LLM_RATE_LIMITED"
    if "quota" in text or "balance" in text or "余额" in text:
        return "LLM_QUOTA_EXHAUSTED"
    return "LLM_UNAVAILABLE"
