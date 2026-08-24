"""Understand：立案 Goal，并在本轮可用工具中做选择（LLM 路径）。

硬规则：
- 不输出 route / skill_id / plan_steps / capability 名；
- 工具调用只允许写 ``use_skill``，且必须落在本轮 enabled_skills 内；
- candidate_capabilities / observation_refs / status 由控制器回填，LLM 不得生效；
- capability 名按注册表语义比对，不因 ``word.word`` 形式误伤普通文本。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from typing import Any, Protocol

from .goal_schema import (
    FORBIDDEN_UNDERSTAND_FIELDS,
    GoalSpec,
    SuccessCriterion,
    UnderstandOutput,
    strip_controller_fields,
)
from .plugin_gates import SkillCatalog

logger = logging.getLogger("bdlh_runtime.cognitive.understand")

_DOTTED_TOKEN = re.compile(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*\b")

_SYSTEM_PROMPT_TEMPLATE = """你是对话 Agent 的理解节点（Understand）。
任务：把用户原句立案为可验证的 goals[]，标出实体、约束、缺口、是否需要外部数据；
并决定本轮的工具调用（action），或 action=null 表示直接回答。

必须只输出一个 JSON 对象，不要 Markdown，不要解释。字段仅允许：
{{
  "goals": [
    {{
      "goal_id": "g1",
      "objective": "本轮要完成的可验证目标（自然语言）",
      "requested_topics": [{topic_enum}],
      "needs_account": false,
      "needs_profile": false,
      "success_criteria": [
        {{"criterion_id": "c1", "topic": null|{topic_enum}, "description": "..."}}
      ]
    }}
  ],
  "entities": {{"instruments": [], "time_range": null}},
  "constraints": [],
  "missing": [],
  "needs_external": false,
  "action": null | {{"tool": "工具名", "parameters": {{...}}}}
}}

禁止输出：route、skill_id、plan_steps、candidate_capabilities、observation_refs、status。
requested_topics 只表达数据主题，不发放权限，也不表示领域路由。
action.tool 只能是用户消息里列出的可用工具名，或 null。
action.parameters 是该工具的参数对象，结构由工具自身约束。
至少包含一个 goal，且每个 goal 至少一个 success_criteria。
"""


class UnderstandModel(Protocol):
    async def understand(
        self,
        message: str,
        *,
        enabled_skills: frozenset[str] | None = None,
    ) -> UnderstandOutput:
        """理解用户原句并返回 UnderstandOutput。"""
        ...


class _LlmChatAdapter:
    """把同步 invoke / 异步 ainvoke 收敛为单一异步端口。"""

    def __init__(self, llm: Any) -> None:
        ainvoke = getattr(llm, "ainvoke", None)
        invoke = getattr(llm, "invoke", None)
        if callable(ainvoke):
            self._call = ainvoke
            self._async = True
        elif callable(invoke):
            self._call = invoke
            self._async = False
        else:
            raise TypeError("LLM must provide ainvoke or invoke")

    async def ainvoke(self, messages: list[dict[str, str]]) -> Any:
        if self._async:
            return await self._call(messages)
        return self._call(messages)


UNDERSTAND_CAPABILITY_SMUGGLED = "UNDERSTAND_CAPABILITY_SMUGGLED"


def _failure_understand(message: str, *, reason_codes: list[str] | None = None) -> UnderstandOutput:
    text = (message or "").strip() or "（空输入）"
    return UnderstandOutput(
        goals=[
            GoalSpec(
                goal_id="g1",
                objective=f"回应用户：{text[:80]}",
                success_criteria=[
                    SuccessCriterion(
                        criterion_id="c1",
                        description="以普通对话完成回答",
                    )
                ],
            )
        ],
        needs_external=False,
        action=None,
        reason_codes=list(reason_codes or []),
    )


class LlmUnderstandModel:
    """LLM Understand；失败或契约不合规时软失败为直接回答。"""

    def __init__(
        self,
        llm: Any,
        *,
        catalog: SkillCatalog | None = None,
        capability_names: Iterable[str] = (),
        allowed_topics: Iterable[str] = (),
    ) -> None:
        self._llm = _LlmChatAdapter(llm)
        self._catalog = catalog or SkillCatalog()
        self._capability_names = frozenset(str(item) for item in capability_names if str(item).strip())
        self._allowed_topics = tuple(str(item) for item in allowed_topics if str(item).strip())
        topic_enum = "|".join(f'"{item}"' for item in self._allowed_topics) or '""'
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(topic_enum=topic_enum)

    async def understand(
        self,
        message: str,
        *,
        enabled_skills: frozenset[str] | None = None,
    ) -> UnderstandOutput:
        text = message.strip()
        if not text:
            return _failure_understand(message)
        try:
            raw = await self._ainvoke_json(text, enabled_skills=enabled_skills)
            parsed, reject_code = _parse_understand_payload(
                raw,
                enabled_skills=enabled_skills,
                catalog=self._catalog,
                capability_names=self._capability_names,
                allowed_topics=self._allowed_topics,
            )
            if parsed is not None:
                return parsed
            if reject_code == UNDERSTAND_CAPABILITY_SMUGGLED:
                return _failure_understand(message, reason_codes=[UNDERSTAND_CAPABILITY_SMUGGLED])
            logger.warning("UNDERSTAND_CONTRACT_INVALID: LLM 输出无法通过契约校验，软失败为直接回答")
        except Exception as exc:  # noqa: BLE001
            logger.warning("UNDERSTAND_LLM_FAILED: %s", type(exc).__name__)
        return _failure_understand(message)

    async def _ainvoke_json(
        self,
        message: str,
        *,
        enabled_skills: frozenset[str] | None = None,
    ) -> str | None:
        user_content = f"{message}\n\n{self._catalog.tool_prompt(enabled_skills)}"
        result = await self._llm.ainvoke(
            [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_content},
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


def create_understand_model(
    llm: Any,
    *,
    catalog: SkillCatalog | None = None,
    capability_names: Iterable[str] = (),
    allowed_topics: Iterable[str] = (),
) -> UnderstandModel:
    """装配 Understand：产品路径必须有 LLM。"""
    if llm is None:
        from bdlh_runtime.runtime.errors import ConfigurationError

        raise ConfigurationError("Understand 需要 LLM；产品路径不允许规则替身装配")
    return LlmUnderstandModel(
        llm,
        catalog=catalog,
        capability_names=capability_names,
        allowed_topics=allowed_topics,
    )


def _parse_understand_payload(
    text: str | None,
    *,
    enabled_skills: frozenset[str] | None = None,
    catalog: SkillCatalog | None = None,
    capability_names: frozenset[str] = frozenset(),
    allowed_topics: tuple[str, ...] = (),
) -> tuple[UnderstandOutput | None, str | None]:
    data = _extract_json(text)
    if not isinstance(data, dict):
        return None, None
    for field in FORBIDDEN_UNDERSTAND_FIELDS:
        if field in data:
            return None, None
    goals_raw = data.get("goals")
    if not isinstance(goals_raw, list) or not goals_raw:
        return None, None
    cleaned_goals: list[dict[str, Any]] = []
    for index, goal in enumerate(goals_raw, start=1):
        if not isinstance(goal, dict):
            return None, None
        for field in FORBIDDEN_UNDERSTAND_FIELDS:
            if field in goal:
                return None, None
        goal_copy = dict(goal)
        goal_copy.pop("status", None)
        goal_copy.pop("observation_refs", None)
        goal_copy.pop("reason_codes", None)
        goal_copy = strip_controller_fields(goal_copy)
        goal_copy.setdefault("goal_id", f"g{index}")
        objective = str(goal_copy.get("objective") or "").strip()
        smuggled = _registered_capability_in_text(objective, capability_names)
        if not objective:
            return None, None
        if smuggled is not None:
            logger.warning("UNDERSTAND_CAPABILITY_SMUGGLED: objective contains %s", smuggled)
            return None, UNDERSTAND_CAPABILITY_SMUGGLED
        topics = goal_copy.get("requested_topics") or []
        if isinstance(topics, list) and allowed_topics:
            goal_copy["requested_topics"] = [item for item in topics if item in allowed_topics]
        criteria = goal_copy.get("success_criteria") or []
        if not isinstance(criteria, list) or not criteria:
            return None, None
        for criterion in criteria:
            if not isinstance(criterion, dict):
                return None, None
            description = str(criterion.get("description") or "")
            smuggled = _registered_capability_in_text(description, capability_names)
            if smuggled is not None:
                logger.warning("UNDERSTAND_CAPABILITY_SMUGGLED: criterion contains %s", smuggled)
                return None, UNDERSTAND_CAPABILITY_SMUGGLED
            topic = criterion.get("topic")
            if allowed_topics and topic not in {None, *allowed_topics}:
                criterion["topic"] = None
        cleaned_goals.append(goal_copy)
    catalog = catalog or SkillCatalog()
    action_raw = data.get("action")
    action: dict[str, Any] | None = None
    if isinstance(action_raw, dict):
        tool = _as_optional_str(action_raw.get("tool"))
        if tool is not None:
            resolved = catalog.resolve_use_skill(tool, enabled_skills)
            if resolved is not None:
                action = {
                    "tool": resolved,
                    "parameters": (
                        action_raw.get("parameters")
                        if isinstance(action_raw.get("parameters"), dict)
                        else {}
                    ),
                }

    payload = {
        "goals": cleaned_goals,
        "entities": data.get("entities") or {},
        "constraints": data.get("constraints") or [],
        "missing": data.get("missing") or [],
        "needs_external": bool(data.get("needs_external", False)),
        "action": action,
    }
    try:
        return UnderstandOutput.model_validate(payload), None
    except Exception:  # noqa: BLE001
        return None, None


def _registered_capability_in_text(text: str, capability_names: frozenset[str]) -> str | None:
    if not text or not capability_names:
        return None
    for match in _DOTTED_TOKEN.finditer(text):
        token = match.group(0)
        if token in capability_names:
            return token
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


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
