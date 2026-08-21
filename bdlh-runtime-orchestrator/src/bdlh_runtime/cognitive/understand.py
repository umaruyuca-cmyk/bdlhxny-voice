"""Understand：立案 Goal（LLM 优先，失败降级规则版）。

硬规则：
- 不输出 route / skill_id / plan_steps / capability / 工具名；
- candidate_capabilities / observation_refs / status 由控制器回填，LLM 不得生效；
- 无 LLM 或解析失败时降级 ``rule_based_understand``，不阻断主流程。
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
    UnderstandEntities,
    UnderstandOutput,
    strip_controller_fields,
)

logger = logging.getLogger("bdlh_runtime.cognitive.understand")

_CODE_PATTERN = re.compile(r"(?<!\d)(?P<code>\d{6})(?!\d)")
_KNOWLEDGE_PATTERN = re.compile(r"(?:什么是|解释一下|是什么意思|有何区别|怎么算|如何理解)")
_SUITABILITY_PATTERN = re.compile(r"(?:适不适合|适合买|能不能买|风险匹配|适当性|适合持有)")
_NEWS_PATTERN = re.compile(r"(?:新闻|舆情|消息)")
_MONEY_FLOW_PATTERN = re.compile(r"(?:资金流|主力|北向)")
_INDUSTRY_PATTERN = re.compile(r"(?:行业|板块|赛道)")
_WEB_PATTERN = re.compile(r"(?:网上|搜索|查一下资料)")
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


def rule_based_understand(message: str, *, goal_id_prefix: str = "g") -> UnderstandOutput:
    """规则版 Understand：无 LLM / 解析失败时的确定性降级。"""
    text = message.strip()
    if not text:
        return UnderstandOutput(
            goals=[
                GoalSpec(
                    goal_id=f"{goal_id_prefix}1",
                    objective="澄清用户意图",
                    success_criteria=[SuccessCriterion(criterion_id="c1", description="获得可执行的目标描述")],
                )
            ],
            missing=["objective"],
            needs_external=False,
        )

    if _KNOWLEDGE_PATTERN.search(text) and _CODE_PATTERN.search(text) is None:
        return UnderstandOutput(
            goals=[
                GoalSpec(
                    goal_id=f"{goal_id_prefix}1",
                    objective=f"解释概念：{text}",
                    success_criteria=[
                        SuccessCriterion(criterion_id="c1", description="给出可核对的概念说明"),
                    ],
                )
            ],
            needs_external=False,
        )

    topics: list[str] = []
    if _NEWS_PATTERN.search(text):
        topics.append("news")
    if _MONEY_FLOW_PATTERN.search(text):
        topics.append("money_flow")
    if _INDUSTRY_PATTERN.search(text):
        topics.append("industry")
    if _WEB_PATTERN.search(text):
        topics.append("web_research")

    code_match = _CODE_PATTERN.search(text)
    instruments = [code_match.group("code")] if code_match else []
    suitability = _SUITABILITY_PATTERN.search(text) is not None

    criteria: list[SuccessCriterion] = []
    if topics:
        for index, topic in enumerate(topics, start=1):
            criteria.append(
                SuccessCriterion(
                    criterion_id=f"t{index}",
                    topic=topic,  # type: ignore[arg-type]
                    description=f"覆盖主题 {topic}",
                )
            )
    else:
        criteria.append(
            SuccessCriterion(
                criterion_id="c1",
                description="获得至少一条非纯解析的业务 Observation",
            )
        )

    missing: list[str] = []
    # 只有金融行情类主题缺标的时才追问；纯 web_research / 普通外部查询不归因「缺股票」
    finance_topics = [topic for topic in topics if topic in {"news", "money_flow", "industry"}]
    if not instruments and not suitability and finance_topics:
        missing.append("instrument")
    elif (
        not instruments
        and not suitability
        and not topics
        and re.search(r"(?:股票|个股|证券|标的|行情|估值|走势)", text)
        and not re.search(r"(?:持仓|组合|我的账户)", text)
    ):
        missing.append("instrument")

    goal = GoalSpec(
        goal_id=f"{goal_id_prefix}1",
        objective=text,
        requested_topics=topics,  # type: ignore[arg-type]
        needs_account=suitability or bool(re.search(r"(?:持仓|组合|账户)", text)),
        needs_profile=suitability,
        success_criteria=criteria,
    )
    return UnderstandOutput(
        goals=[goal],
        entities=UnderstandEntities(instruments=instruments),
        missing=missing,
        needs_external=True,
    )


class RuleBasedUnderstandModel:
    """异步包装规则 Understand，便于统一装配。"""

    async def understand(self, message: str) -> UnderstandOutput:
        return rule_based_understand(message)


class LlmUnderstandModel:
    """LLM Understand；失败或契约不合规时降级规则版。"""

    def __init__(self, llm: Any, *, fallback: UnderstandModel | None = None):
        self._llm = llm
        self._fallback = fallback or RuleBasedUnderstandModel()

    async def understand(self, message: str) -> UnderstandOutput:
        text = message.strip()
        if not text:
            return await self._fallback.understand(message)
        try:
            raw = await self._ainvoke_json(text)
            parsed = _parse_understand_payload(raw)
            if parsed is not None:
                return parsed
            logger.warning("Understand LLM 输出无法通过契约校验，降级规则版")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Understand LLM 调用失败，降级规则版: %s", type(exc).__name__)
        return await self._fallback.understand(message)

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


def create_understand_model(llm: Any | None) -> UnderstandModel:
    """装配 Understand：有 LLM 用 LLM，否则规则版。"""
    if llm is None:
        return RuleBasedUnderstandModel()
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
