"""理解 Agent：goals[] 立案，不做工具选择（重写 §4/§6.2）。

理解节点 ``tools = []``：禁止输出 route / skill_id / analysis_type /
plan_steps / 任何 capability 名。LLM 只产出目标、实体、约束、缺口、
是否需要外部工具；``candidate_capabilities`` 由控制器回填。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from pydantic import ValidationError

from bdlh_runtime.cognitive.goal_schema import (
    GoalSpec,
    SuccessCriterion,
    UnderstandEntities,
    UnderstandOutput,
    strip_controller_fields,
)

logger = logging.getLogger("bdlh_runtime.agents.query")

_SYMBOL_PATTERN = re.compile(r"(?<!\d)([0369]\d{5})(?!\d)")

_TOPIC_TRIGGERS: list[tuple[str, tuple[str, ...]]] = [
    ("news", ("新闻", "消息", "公告", "舆情", "事件")),
    ("money_flow", ("资金流", "资金", "主力", "流入", "流出")),
    ("industry", ("行业", "板块", "同业", "赛道")),
    ("web_research", ("最新", "联网", "全网", "查一下网")),
]

_ACCOUNT_TRIGGERS = ("我的持仓", "我的账户", "对照账户", "对照持仓", "持仓", "账户", "组合")
_PROFILE_TRIGGERS = ("风险画像", "我的风险", "画像", "风险承受")
_KNOWLEDGE_TRIGGERS = ("什么是", "解释一下", "解释", "定义", "含义", "什么意思", "怎么理解", "是指")
_SYMBOL_ANALYSIS_TRIGGERS = ("分析", "走势", "市盈率", "估值", "基本面", "技术", "报价", "多少钱", "行情", "K线")


class UnderstandAgent(Protocol):
    """生产理解 Agent 接口；后续可替换为结构化 LLM 调用。"""

    def understand(self, request: dict[str, Any], extra_context: dict[str, Any] | None = None) -> UnderstandOutput:
        """仅理解用户请求，禁止查询外部系统、禁止选择工具。"""
        ...


def _extract_topics(message: str) -> list[str]:
    topics: list[str] = []
    for topic, keywords in _TOPIC_TRIGGERS:
        if any(word in message for word in keywords):
            topics.append(topic)
    return topics


def _rule_based_understand(request: dict[str, Any]) -> UnderstandOutput:
    """规则降级：无 LLM 时立案单一 Goal，不猜体裁、不选工具。"""
    message = str(request.get("message", "")).strip()
    symbols = _SYMBOL_PATTERN.findall(message)
    explicit_symbol = request.get("symbol")
    instruments = list(dict.fromkeys(symbols)) or ([str(explicit_symbol)] if explicit_symbol else [])

    needs_account = any(word in message for word in _ACCOUNT_TRIGGERS)
    needs_profile = any(word in message for word in _PROFILE_TRIGGERS)
    is_knowledge = any(word in message for word in _KNOWLEDGE_TRIGGERS)

    goals: list[GoalSpec] = []
    topics = _extract_topics(message)

    # 研究型 Goal：问话本身（含对比多标的）；知识问答不立案外部 Goal
    if not is_knowledge or instruments:
        criteria = [
            SuccessCriterion(
                criterion_id="c-research",
                topic=topic,
                description=f"获得 {topic} 相关的有证据数据",
            )
            for topic in topics
        ] or [
            SuccessCriterion(
                criterion_id="c-research",
                topic=None,
                description="给出有证据的回答",
            )
        ]
        goals.append(
            GoalSpec(
                goal_id="g-research",
                objective=message or "分析用户询问的标的",
                requested_topics=topics,
                success_criteria=criteria,
            )
        )
    if needs_account:
        goals.append(
            GoalSpec(
                goal_id="g-account",
                objective="读取用户持仓/账户事实以对照",
                needs_account=True,
                success_criteria=[
                    SuccessCriterion(
                        criterion_id="c-account",
                        topic=None,
                        description="获得用户持仓/账户数据",
                    )
                ],
            )
        )
    if needs_profile:
        goals.append(
            GoalSpec(
                goal_id="g-profile",
                objective="读取用户风险画像以结合判断",
                needs_profile=True,
                success_criteria=[
                    SuccessCriterion(
                        criterion_id="c-profile",
                        topic=None,
                        description="获得用户风险画像数据",
                    )
                ],
            )
        )
    if not goals:
        goals.append(
            GoalSpec(
                goal_id="g-answer",
                objective=message or "回答用户问题",
                success_criteria=[
                    SuccessCriterion(criterion_id="c-answer", topic=None, description="给出回答")
                ],
            )
        )

    return UnderstandOutput(
        goals=goals,
        entities=UnderstandEntities(instruments=instruments),
        constraints=[],
        missing=(
            ["symbol"]
            if (not instruments and not is_knowledge and not needs_account
                and any(word in message for word in _SYMBOL_ANALYSIS_TRIGGERS))
            else []
        ),
        needs_external=bool(instruments) or needs_account or needs_profile or bool(topics),
    )


class RuleBasedUnderstandAgent:
    """确定性替身：无 LLM 环境与 LLM 失败时的降级实现。"""

    def understand(self, request: dict[str, Any], extra_context: dict[str, Any] | None = None) -> UnderstandOutput:
        return _rule_based_understand(request)


# ── LLM 版：结构化输出 + 控制器字段剥离 ──

_UNDERSTAND_SYSTEM_PROMPT = (
    "你是用户请求理解器。只输出 JSON，不要解释。"
    "字段：goals（数组，每项 {goal_id, objective, requested_topics, needs_account, needs_profile, "
    "success_criteria:[{criterion_id, topic, description}]}），"
    "entities（{instruments, time_range}），constraints（数组），missing（数组），"
    "needs_external（bool）。"
    "requested_topics 只允许 news/money_flow/industry/web_research 或空，"
    "禁止 valuation/technical/comprehensive 等体裁词。"
    "禁止输出 route、skill_id、analysis_type、plan_steps 或任何工具名。"
    "复合问题（对比+对照账户）拆多个 goal。"
    "问话涉及对照持仓/账户 → needs_account=true；涉及风险画像 → needs_profile=true。"
)

_UNDERSTAND_USER_TEMPLATE = "用户问题：{message}"


class LlmUnderstandAgent:
    """基于 LLM 的理解实现；失败降级规则版。"""

    def __init__(self, llm: Any | None):
        self._llm = llm
        self._fallback = RuleBasedUnderstandAgent()

    def understand(self, request: dict[str, Any], extra_context: dict[str, Any] | None = None) -> UnderstandOutput:
        if self._llm is None:
            return self._fallback.understand(request)
        message = str(request.get("message", ""))
        if not message:
            return self._fallback.understand(request)
        try:
            user_content = _UNDERSTAND_USER_TEMPLATE.format(message=message)
            if extra_context:
                lines = []
                profile = extra_context.get("user_profile") or {}
                if profile:
                    lines.append(f"用户画像：{profile}")
                memories = extra_context.get("recalled_memories") or []
                if memories:
                    lines.append(f"历史记忆：{[m.get('content', '') for m in memories]}")
                if lines:
                    user_content += "\n\n参考上下文：\n" + "\n".join(lines)
            response = self._llm.invoke([
                {"role": "system", "content": _UNDERSTAND_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ])
            raw = response.content if hasattr(response, "content") else str(response)
            data = json.loads(_extract_json(raw))
            for goal in data.get("goals", []) or []:
                strip_controller_fields(goal)
            if not data.get("entities"):
                data["entities"] = {"instruments": _SYMBOL_PATTERN.findall(message) or ([str(request["symbol"])] if request.get("symbol") else [])}
            return UnderstandOutput(**data)
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            logger.warning("LLM 理解解析失败，降级规则版: %s", exc)
            return self._fallback.understand(request)


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.split("\n") if not ln.strip().startswith("```")]
        return "\n".join(lines)
    return text


def create_understand_agent(llm: Any | None) -> UnderstandAgent:
    """工厂：有 LLM 用 LLM 版，无 LLM 用规则版。"""
    return LlmUnderstandAgent(llm) if llm is not None else RuleBasedUnderstandAgent()
