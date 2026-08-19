"""Research Agent 的行动契约与实现（重写 §6.2）。

Agent 只在窗口内选择下一步只读统一能力；Tool Runtime 和
MarketDataGateway 负责实际执行、预算和数据源路由。

两种实现：
- RuleBasedResearchAgent：按 PENDING Goal 的 candidate_capabilities + depends_on
  选下一步；Goal 全部 COVERED/BLOCKED 才 finish。
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

    def choose_next_action(
        self,
        observations: list[dict],
        allowed_specs: list[dict],
        *,
        goals: list[dict] | None = None,
    ) -> ResearchAction:
        """仅提出一个只读统一工具动作；不得直接执行工具。"""
        ...


#: 纯前置解析能力：作为依赖步骤先做，但不作为业务目标
DEPENDENCY_ONLY_CAPABILITIES = {"market.resolve_instrument"}

#: 重型可选能力：规则版 Agent 不自动点选（须由调用策略 / LLM 显式选择）
HEAVY_OPTIONAL_CAPABILITIES = {"research.deep_search"}


class RuleBasedResearchAgent:
    """确定性路径：PENDING Goal 候选优先，再闭包前置，全 settled 才 finish。"""

    def choose_next_action(
        self,
        observations: list[dict],
        allowed_specs: list[dict],
        *,
        goals: list[dict] | None = None,
    ) -> ResearchAction:
        fulfilled = {
            obs.get("capability")
            for obs in observations
            if obs.get("status") in {"SUCCESS", "PARTIAL"}
        }
        by_name = {spec.get("name", ""): spec for spec in allowed_specs}
        allowed_names = set(by_name)

        pending_candidates = _pending_goal_candidates(goals)
        if pending_candidates:
            # 1. Goal 候选的 depends_on 前置
            for name in pending_candidates:
                spec = by_name.get(name)
                if not spec or name in fulfilled:
                    continue
                deps = spec.get("depends_on") or []
                missing = [dep for dep in deps if dep and dep not in fulfilled]
                if missing:
                    dep = missing[0]
                    if dep in allowed_names:
                        return ResearchAction(
                            action=dep,
                            arguments=self._arguments_for(by_name.get(dep)),
                            reason=f"前置能力 {dep} 未满足（Goal 依赖闭包）",
                        )
            # 2. Goal 候选本身
            for name in pending_candidates:
                if name in fulfilled or name not in allowed_names:
                    continue
                if name in HEAVY_OPTIONAL_CAPABILITIES:
                    continue
                return ResearchAction(
                    action=name,
                    arguments=self._arguments_for(by_name.get(name)),
                    reason=f"覆盖 PENDING Goal：获取 {name}",
                )

        # 无 PENDING 候选：兼容旧路径（无 goals 时扫业务能力）
        if not goals:
            for spec in allowed_specs:
                name = spec.get("name", "")
                if name in fulfilled:
                    continue
                deps = spec.get("depends_on") or []
                if any(dep and dep not in fulfilled for dep in deps):
                    missing_dep = next(dep for dep in deps if dep and dep not in fulfilled)
                    if missing_dep in allowed_names:
                        return ResearchAction(
                            action=missing_dep,
                            arguments=self._arguments_for(by_name.get(missing_dep)),
                            reason=f"前置能力 {missing_dep} 未满足（依赖闭包）",
                        )
            for spec in allowed_specs:
                name = spec.get("name", "")
                if not name or name in DEPENDENCY_ONLY_CAPABILITIES or name in fulfilled:
                    continue
                if name in HEAVY_OPTIONAL_CAPABILITIES:
                    continue
                return ResearchAction(
                    action=name,
                    arguments=self._arguments_for(spec),
                    reason=f"获取 {name} 数据",
                )

        return ResearchAction(
            action="finish",
            arguments={},
            reason="Goal 已 settled 或无可选候选能力",
        )

    @staticmethod
    def _arguments_for(spec: dict | None) -> dict:
        if not spec:
            return {}
        return {arg: None for arg in spec.get("required_arguments", [])} or {}


def _pending_goal_candidates(goals: list[dict] | None) -> list[str]:
    if not goals:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for goal in goals:
        if str(goal.get("status") or "PENDING") != "PENDING":
            continue
        for criterion in goal.get("success_criteria") or []:
            if not isinstance(criterion, dict):
                continue
            for name in criterion.get("candidate_capabilities") or []:
                text = str(name)
                if text and text not in seen:
                    seen.add(text)
                    ordered.append(text)
        if goal.get("needs_account") or goal.get("needs_profile"):
            # 候选已在 backfill 写入 success_criteria；此处无需额外前缀扫描
            continue
    return ordered


# ── LLM 版 ──
_RESEARCH_SYSTEM_PROMPT = (
    "你是市场数据获取决策器。只能从用户消息提供的窗口内统一能力中选择下一个只读能力。"
    "只输出 JSON：{\"action\": \"统一能力名\", \"arguments\": {...}, \"reason\": \"原因\"}。"
    "当 Goal 均已 COVERED/BLOCKED 时输出 {\"action\": \"finish\"}；"
    "若仍有 PENDING Goal，不得 finish，应选择能覆盖该 Goal 的窗口内能力。"
    "不得发明能力名，不得输出 MCP 原始工具名、写操作或非数据工具。"
    "若窗口同时有 research.web_search 与 research.deep_search："
    "普通查询/单点事实用 web_search；仅当用户明确要求深度调研/交叉验证/多主题比较，"
    "或需要多条可验证成功条件时才选 deep_search。"
    "选择 deep_search 时 arguments 需含 question 与 objective；不要把入口主题自动升级为深度研究。"
)


class LlmResearchAgent:
    """窗口内有界 ReAct Agent；越窗或失败降级规则版。"""

    def __init__(self, llm: Any | None):
        self._llm = llm
        self._fallback = RuleBasedResearchAgent()

    def choose_next_action(
        self,
        observations: list[dict],
        allowed_specs: list[dict],
        *,
        goals: list[dict] | None = None,
    ) -> ResearchAction:
        if self._llm is None:
            return self._fallback.choose_next_action(
                observations, allowed_specs, goals=goals
            )

        try:
            obs_summary = self._format_observations(observations)
            req_summary = self._format_candidates(allowed_specs)
            goals_summary = self._format_goals(goals)
            response = self._llm.invoke([
                {"role": "system", "content": _RESEARCH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Goals：\n{goals_summary}\n\n"
                        f"已有观测：\n{obs_summary}\n\n窗口候选：\n{req_summary}"
                    ),
                },
            ])
            raw = response.content if hasattr(response, "content") else str(response)
            data = json.loads(self._extract_json(raw))
            action = ResearchAction(**data)
            allowed = {str(spec.get("name")) for spec in allowed_specs if spec.get("name")}
            if not action.is_finish and action.action not in allowed:
                logger.warning("LLM 选择了窗口外能力 %s，降级回规则版", action.action)
                return self._fallback.choose_next_action(
                    observations, allowed_specs, goals=goals
                )
            if action.is_finish and _has_pending_goals(goals):
                logger.warning("LLM 在 PENDING Goal 上 finish，降级回规则版")
                return self._fallback.choose_next_action(
                    observations, allowed_specs, goals=goals
                )
            return action
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            logger.warning("LLM ReAct 决策失败，降级回规则版: %s", exc)
            return self._fallback.choose_next_action(
                observations, allowed_specs, goals=goals
            )

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
            lines.append(
                f"  - {spec.get('name', '?')} 需要参数 {spec.get('required_arguments', [])}{suffix}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_goals(goals: list[dict] | None) -> str:
        if not goals:
            return "（无 Goal）"
        lines = []
        for goal in goals:
            lines.append(
                f"  - {goal.get('goal_id')}: status={goal.get('status')} "
                f"objective={goal.get('objective')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = [ln for ln in text.split("\n") if not ln.strip().startswith("```")]
            return "\n".join(lines)
        return text


def _has_pending_goals(goals: list[dict] | None) -> bool:
    return any(str(goal.get("status") or "PENDING") == "PENDING" for goal in (goals or []))


def create_research_agent(llm: Any | None) -> ResearchAgent:
    """工厂：有 LLM 用 LLM 版（窗口有界），无 LLM 用规则版。"""
    return LlmResearchAgent(llm) if llm is not None else RuleBasedResearchAgent()
