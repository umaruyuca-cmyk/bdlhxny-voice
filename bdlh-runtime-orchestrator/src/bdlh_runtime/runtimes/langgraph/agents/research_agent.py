"""Research Agent 的行动契约与实现（重写 §6.2）。

Agent 只在窗口内选择下一步只读统一能力；Tool Runtime 和
MarketDataGateway 负责实际执行、预算和数据源路由。

两种实现：
- RuleBasedResearchAgent：确定性路径——先满足 depends_on 前置，再按
  PENDING goal 需要的业务能力顺序选择；全部可用即 finish。
- LlmResearchAgent：有 LLM 时在窗口候选内自主选择；越窗即降级规则版。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("bdlh_runtime.agents.research")


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

    def choose_next_action(self, observations: list[dict], allowed_specs: list[dict]) -> ResearchAction:
        """仅提出一个只读统一工具动作；不得直接执行工具。"""
        ...


#: 纯前置解析能力：作为依赖步骤先做，但不作为业务目标
DEPENDENCY_ONLY_CAPABILITIES = {"market.resolve_instrument"}


class RuleBasedResearchAgent:
    """确定性路径：先闭包前置、再业务能力，全部可用即 finish。"""

    def choose_next_action(self, observations: list[dict], allowed_specs: list[dict]) -> ResearchAction:
        fulfilled = {
            obs.get("capability")
            for obs in observations
            if obs.get("status") in {"SUCCESS", "PARTIAL"}
        }
        by_name = {spec.get("name", ""): spec for spec in allowed_specs}

        # 1. 未满足的 depends_on 前置优先（确定性闭包，不靠相似度）
        for spec in allowed_specs:
            name = spec.get("name", "")
            if name in fulfilled:
                continue
            deps = spec.get("depends_on") or []
            if any(dep and dep not in fulfilled for dep in deps):
                missing_dep = next(dep for dep in deps if dep and dep not in fulfilled)
                return ResearchAction(
                    action=missing_dep,
                    arguments=self._arguments_for(by_name.get(missing_dep)),
                    reason=f"前置能力 {missing_dep} 未满足（依赖闭包）",
                )

        # 2. 第一个尚无可用 Observation 的业务能力（排除纯前置）
        for spec in allowed_specs:
            name = spec.get("name", "")
            if not name or name in DEPENDENCY_ONLY_CAPABILITIES or name in fulfilled:
                continue
            return ResearchAction(
                action=name,
                arguments=self._arguments_for(spec),
                reason=f"获取 {name} 数据",
            )

        return ResearchAction(action="finish", arguments={}, reason="所有可用能力均已执行")

    @staticmethod
    def _arguments_for(spec: dict | None) -> dict:
        if not spec:
            return {}
        return {arg: None for arg in spec.get("required_arguments", [])} or {}


# ── LLM 版 ──
_RESEARCH_SYSTEM_PROMPT = (
    "你是市场数据获取决策器。只能从用户消息提供的窗口内统一能力中选择下一个只读能力。"
    "只输出 JSON：{\"action\": \"统一能力名\", \"arguments\": {...}, \"reason\": \"原因\"}。"
    "所有需要的数据已获取时输出 {\"action\": \"finish\"}。"
    "不得发明能力名，不得输出 MCP 原始工具名、写操作或非数据工具。"
)


class LlmResearchAgent:
    """窗口内有界 ReAct Agent；越窗或失败降级规则版。"""

    def __init__(self, llm: Any | None):
        self._llm = llm
        self._fallback = RuleBasedResearchAgent()

    def choose_next_action(self, observations: list[dict], allowed_specs: list[dict]) -> ResearchAction:
        if self._llm is None:
            return self._fallback.choose_next_action(observations, allowed_specs)

        try:
            obs_summary = self._format_observations(observations)
            req_summary = self._format_candidates(allowed_specs)
            response = self._llm.invoke([
                {"role": "system", "content": _RESEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": f"已有观测：\n{obs_summary}\n\n窗口候选：\n{req_summary}"},
            ])
            raw = response.content if hasattr(response, "content") else str(response)
            data = json.loads(self._extract_json(raw))
            action = ResearchAction(**data)
            allowed = {str(spec.get("name")) for spec in allowed_specs if spec.get("name")}
            if not action.is_finish and action.action not in allowed:
                logger.warning("LLM 选择了窗口外能力 %s，降级回规则版", action.action)
                return self._fallback.choose_next_action(observations, allowed_specs)
            return action
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            logger.warning("LLM ReAct 决策失败，降级回规则版: %s", exc)
            return self._fallback.choose_next_action(observations, allowed_specs)

    @staticmethod
    def _format_observations(observations: list[dict]) -> str:
        if not observations:
            return "（暂无）"
        lines = []
        for obs in observations:
            lines.append(f"  - {obs.get('capability', '?')}: {obs.get('status', '?')}")
        return "\n".join(lines)

    @staticmethod
    def _format_candidates(allowed_specs: list[dict]) -> str:
        if not allowed_specs:
            return "（窗口为空）"
        lines = []
        for spec in allowed_specs:
            deps = spec.get("depends_on") or []
            suffix = f"（前置: {','.join(deps)}）" if deps else ""
            lines.append(f"  - {spec.get('name', '?')} 需要参数 {spec.get('required_arguments', [])}{suffix}")
        return "\n".join(lines)

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = [ln for ln in text.split("\n") if not ln.strip().startswith("```")]
            return "\n".join(lines)
        return text


def create_research_agent(llm: Any | None) -> ResearchAgent:
    """工厂：有 LLM 用 LLM 版（窗口有界），无 LLM 用规则版。"""
    return LlmResearchAgent(llm) if llm is not None else RuleBasedResearchAgent()
