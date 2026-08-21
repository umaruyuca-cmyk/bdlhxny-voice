"""Understand：立案 Goal（LLM 路径）。

硬规则：
- 不输出 route / skill_id / plan_steps / capability / 工具名；
- candidate_capabilities / observation_refs / status 由控制器回填，LLM 不得生效；
- 解析/调用失败时软失败为「需澄清」UnderstandOutput，不降级关键词金融路由。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from .goal_schema import (
    FORBIDDEN_UNDERSTAND_FIELDS,
    GoalSpec,
    SuccessCriterion,
    UnderstandOutput,
    strip_controller_fields,
)

logger = logging.getLogger("bdlh_runtime.cognitive.understand")

_CAPABILITY_NAME_PATTERN = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*\b")

_SYSTEM_PROMPT = """你是 BDLH Agent Runtime 的理解节点（Understand）。
任务：把用户原句立案为可验证的 goals[]，并标出实体、约束、缺口、是否需要外部数据。

必须只输出一个 JSON 对象，不要 Markdown，不要解释。字段仅允许：
{
  "goals": [
    {
      "goal_id": "g1",
      "objective": "本轮要完成的可验证目标（自然语言）",
      "requested_topics": ["news"|"money_flow"|"industry"|"web_research"],
      "needs_account": false,
      "needs_profile": false,
      "success_criteria": [
        {"criterion_id": "c1", "topic": null|"news"|"money_flow"|"industry"|"web_research", "description": "..."}
      ]
    }
  ],
  "entities": {"instruments": ["600519"], "time_range": null},
  "constraints": [],
  "missing": ["instrument"],
  "needs_external": true
}

禁止输出：route、skill_id、plan_steps、任何 capability/工具名、candidate_capabilities、observation_refs、status。
requested_topics 只表达数据主题，不发放权限。
纯概念问答（如“什么是市盈率”）设 needs_external=false；需要行情/持仓/外部资料时 needs_external=true。
至少包含一个 goal，且每个 goal 至少一个 success_criteria。
"""


class UnderstandModel(Protocol):
    async def understand(self, message: str) -> UnderstandOutput:
        """理解用户原句并返回 UnderstandOutput。"""
        ...


def _failure_understand(message: str) -> UnderstandOutput:
    """LLM 不可用/不合规时的软失败：迫使编排走澄清，不关键词路由金融。"""
    text = (message or "").strip() or "（空输入）"
    return UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective=f"澄清用户意图：{text[:80]}",
                success_criteria=[
                    SuccessCriterion(
                        criterion_id="c1",
                        description="获得可执行的目标描述",
                    )
                ],
            )
        ],
        missing=["理解失败"],
        needs_external=False,
    )


class LlmUnderstandModel:
    """LLM Understand；失败或契约不合规时软失败为澄清输出。"""

    def __init__(self, llm: Any):
        self._llm = llm

    async def understand(self, message: str) -> UnderstandOutput:
        text = message.strip()
        if not text:
            return _failure_understand(message)
        try:
            raw = await self._ainvoke_json(text)
            parsed = _parse_understand_payload(raw)
            if parsed is not None:
                return parsed
            logger.warning("Understand LLM 输出无法通过契约校验，软失败为澄清")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Understand LLM 调用失败，软失败为澄清: %s", type(exc).__name__)
        return _failure_understand(message)

    async def _ainvoke_json(self, message: str) -> str | None:
        invoke = getattr(self._llm, "ainvoke", None)
        if callable(invoke):
            result = await invoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ]
            )
        else:
            result = self._llm.invoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ]
            )
        content = getattr(result, "content", result)
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(str(getattr(item, "text", item)))
            return "\n".join(parts)
        return str(content) if content is not None else None


def create_understand_model(llm: Any) -> UnderstandModel:
    """装配 Understand：产品路径必须有 LLM。"""
    if llm is None:
        from bdlh_runtime.runtime.errors import ConfigurationError

        raise ConfigurationError("Understand 需要 LLM；产品路径不允许规则替身装配")
    return LlmUnderstandModel(llm)


def _parse_understand_payload(text: str | None) -> UnderstandOutput | None:
    data = _extract_json(text)
    if not isinstance(data, dict):
        return None
    for field in FORBIDDEN_UNDERSTAND_FIELDS:
        if field in data:
            return None
    goals_raw = data.get("goals")
    if not isinstance(goals_raw, list) or not goals_raw:
        return None
    cleaned_goals: list[dict[str, Any]] = []
    for index, goal in enumerate(goals_raw, start=1):
        if not isinstance(goal, dict):
            return None
        for field in FORBIDDEN_UNDERSTAND_FIELDS:
            if field in goal:
                return None
        goal_copy = dict(goal)
        goal_copy.pop("status", None)
        goal_copy.pop("observation_refs", None)
        goal_copy = strip_controller_fields(goal_copy)
        goal_copy.setdefault("goal_id", f"g{index}")
        objective = str(goal_copy.get("objective") or "").strip()
        if not objective or _CAPABILITY_NAME_PATTERN.search(objective):
            return None
        criteria = goal_copy.get("success_criteria") or []
        if not isinstance(criteria, list) or not criteria:
            return None
        for criterion in criteria:
            if not isinstance(criterion, dict):
                return None
            description = str(criterion.get("description") or "")
            if _CAPABILITY_NAME_PATTERN.search(description):
                return None
        cleaned_goals.append(goal_copy)
    payload = {
        "goals": cleaned_goals,
        "entities": data.get("entities") or {},
        "constraints": data.get("constraints") or [],
        "missing": data.get("missing") or [],
        "needs_external": bool(data.get("needs_external", False)),
    }
    try:
        return UnderstandOutput.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None


def _extract_json(text: str | None) -> Any | None:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start_obj = text.find("{")
    if start_obj < 0:
        return None
    snippet = text[start_obj:]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        end = snippet.rfind("}")
        if end < 0:
            return None
        try:
            return json.loads(snippet[: end + 1])
        except json.JSONDecodeError:
            return None
