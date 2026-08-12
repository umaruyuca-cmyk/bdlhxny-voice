"""Research Agent 的行动契约与实现。

Phase 2 接入真实 MCP 后，该 Agent 只能提出一个统一工具动作；Tool Runtime 和
MarketDataGateway 负责实际执行、预算和数据源路由。

本文件提供两种实现：
- RuleBasedResearchAgent：确定性快路径，按 DataRequirement 顺序选下一个未满足
  的能力。market_snapshot/technical/fundamental 等非 comprehensive 类型走这条
  （Prompt §8 执行矩阵），不经 LLM 自主决策，保证可测、省钱。
- LlmResearchAgent：comprehensive 类型走这条，LLM 根据已有 Observation 和剩余
  需求自主选下一步。无 LLM 时降级回规则版。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("stockwise_analysis.agents.research")


class ResearchAction(BaseModel):
    """有界 ReAct 单轮允许输出的唯一行动。"""

    action: str  # 统一能力名，如 market.get_historical_prices
    arguments: dict = Field(default_factory=dict)
    reason: str

    @property
    def is_finish(self) -> bool:
        """是否为"结束"动作（无更多数据需要获取）。"""
        return self.action == "finish"


class ResearchAgent(Protocol):
    """市场数据子图的有界 Agent 接口。"""

    def choose_next_action(self, observations: list[dict], remaining_requirements: list[dict]) -> ResearchAction:
        """仅提出一个只读统一工具动作；不得直接执行工具。"""
        ...


class RuleBasedResearchAgent:
    """确定性快路径：按 DataRequirement 顺序选择下一个未满足的能力。

    遍历 remaining_requirements，找到第一个还没对应 Observation 的能力，
    输出调用它的 ResearchAction。全部满足时返回 finish。

    这是 market_snapshot/technical/fundamental/valuation 类型的默认路径
    （Prompt §8 执行矩阵：优先固定数据计划，不经 LLM 自适应）。
    """

    def choose_next_action(self, observations: list[dict], remaining_requirements: list[dict]) -> ResearchAction:
        # 已获取的能力集合
        fulfilled = {obs.get("capability") for obs in observations if obs.get("status") == "SUCCESS"}

        for req in remaining_requirements:
            capability = req.get("capability", "")
            if capability and capability not in fulfilled:
                return ResearchAction(
                    action=capability,
                    arguments=req.get("arguments", {}),
                    reason=req.get("reason", f"获取 {capability} 数据"),
                )

        return ResearchAction(action="finish", arguments={}, reason="所有数据需求已满足")


# ── LLM 版（comprehensive 类型用）──
_RESEARCH_SYSTEM_PROMPT = (
    "你是市场数据获取决策器。只能从用户消息提供的剩余统一能力中选择下一个只读能力。"
    "只输出 JSON：{\"action\": \"统一能力名\", \"arguments\": {...}, \"reason\": \"原因\"}。"
    "所有需求满足时输出 {\"action\": \"finish\"}。不得发明能力名，不得输出 MCP 原始工具名、写操作或非数据工具。"
)


class LlmResearchAgent:
    """comprehensive 类型的有界 ReAct Agent。

    有 LLM 时让模型根据已有 Observation 自主决策下一步；无 LLM 或失败时
    降级回 RuleBasedResearchAgent。降级保证数据子图始终能推进。
    """

    def __init__(self, llm: Any | None):
        self._llm = llm
        self._fallback = RuleBasedResearchAgent()

    def choose_next_action(self, observations: list[dict], remaining_requirements: list[dict]) -> ResearchAction:
        if self._llm is None:
            return self._fallback.choose_next_action(observations, remaining_requirements)

        try:
            obs_summary = self._format_observations(observations)
            req_summary = self._format_requirements(remaining_requirements)
            response = self._llm.invoke([
                {"role": "system", "content": _RESEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": f"已有观测：\n{obs_summary}\n\n剩余需求：\n{req_summary}"},
            ])
            raw = response.content if hasattr(response, "content") else str(response)
            data = json.loads(self._extract_json(raw))
            action = ResearchAction(**data)
            allowed = {
                str(item.get("capability"))
                for item in remaining_requirements
                if item.get("capability")
            }
            if not action.is_finish and action.action not in allowed:
                logger.warning("LLM 选择了候选白名单外能力 %s，降级回规则版", action.action)
                return self._fallback.choose_next_action(observations, remaining_requirements)
            return action
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            logger.warning("LLM ReAct 决策失败，降级回规则版: %s", exc)
            return self._fallback.choose_next_action(observations, remaining_requirements)

    @staticmethod
    def _format_observations(observations: list[dict]) -> str:
        if not observations:
            return "（暂无）"
        lines = []
        for obs in observations:
            cap = obs.get("capability", "?")
            status = obs.get("status", "?")
            lines.append(f"  - {cap}: {status}")
        return "\n".join(lines)

    @staticmethod
    def _format_requirements(requirements: list[dict]) -> str:
        if not requirements:
            return "（全部满足）"
        lines = []
        for req in requirements:
            cap = req.get("capability", "?")
            args = req.get("arguments", {})
            lines.append(f"  - {cap} {args}")
        return "\n".join(lines)

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            return "\n".join(lines)
        return text


def create_research_agent(llm: Any | None, analysis_type: str = "") -> ResearchAgent:
    """工厂函数：comprehensive 用 LLM 版，其他用规则版。

    按 Prompt §8 执行矩阵：只有 comprehensive 走完整 ReAct（LLM 自主决策），
    其他类型走确定性快路径（规则版）。
    """
    if analysis_type == "comprehensive" and llm is not None:
        return LlmResearchAgent(llm)
    return RuleBasedResearchAgent()
