"""Tests-only rule-based Understand — not a product path."""

from __future__ import annotations

import re

from bdlh_runtime.cognitive.goal_schema import (
    GoalSpec,
    SuccessCriterion,
    UnderstandEntities,
    UnderstandOutput,
)

_CODE_PATTERN = re.compile(r"(?<!\d)(?P<code>\d{6})(?!\d)")
_KNOWLEDGE_PATTERN = re.compile(r"(?:什么是|解释一下|是什么意思|有何区别|怎么算|如何理解)")
_SUITABILITY_PATTERN = re.compile(r"(?:适不适合|适合买|能不能买|风险匹配|适当性|适合持有)")
_NEWS_PATTERN = re.compile(r"(?:新闻|舆情|消息)")
_MONEY_FLOW_PATTERN = re.compile(r"(?:资金流|主力|北向)")
_INDUSTRY_PATTERN = re.compile(r"(?:行业|板块|赛道)")
_WEB_PATTERN = re.compile(r"(?:网上|搜索|查一下资料)")


def rule_based_understand(message: str, *, goal_id_prefix: str = "g") -> UnderstandOutput:
    """规则版 Understand：隔离单测的确定性替身。"""
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
