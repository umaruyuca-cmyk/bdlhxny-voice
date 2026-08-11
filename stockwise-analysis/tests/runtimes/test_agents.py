"""Agent LLM 实现与降级测试。

验证：无 LLM 时各 Agent 降级为规则版且行为正确；LLM 调用失败时也降级。
"""

from __future__ import annotations

from stockwise_analysis.contracts.analysis import AnalysisResult
from stockwise_analysis.runtimes.langgraph.agents.query_agent import (
    LlmQueryAgent,
    RuleBasedQueryAgent,
    create_query_agent,
)
from stockwise_analysis.runtimes.langgraph.agents.research_agent import (
    RuleBasedResearchAgent,
    create_research_agent,
)
from stockwise_analysis.runtimes.langgraph.agents.summary_model import (
    DeterministicSummaryModel,
    LlmSummaryModel,
    create_summary_model,
)


# ── Query Agent ──


def test_query_agent_factory_no_llm_returns_rule_based():
    """无 LLM 时工厂返回 RuleBasedQueryAgent。"""
    agent = create_query_agent(None)
    assert isinstance(agent, RuleBasedQueryAgent)


def test_llm_query_agent_falls_back_when_no_llm():
    """LlmQueryAgent 无 LLM 时降级为规则版行为。"""
    agent = LlmQueryAgent(None)
    intent = agent.understand({"message": "分析 600519 技术面"})
    assert intent.symbol == "600519"
    assert intent.analysis_type == "technical"


def test_llm_query_agent_falls_back_on_llm_error():
    """LLM 调用异常时降级为规则版，不抛错。"""

    class FakeLlm:
        def invoke(self, messages):
            raise RuntimeError("模拟 LLM 故障")

    agent = LlmQueryAgent(FakeLlm())
    intent = agent.understand({"message": "600519 综合分析"})
    assert intent.symbol == "600519"
    assert intent.analysis_type == "comprehensive"


# ── Summary Model ──


def test_summary_model_factory_no_llm_returns_deterministic():
    """无 LLM 时工厂返回 DeterministicSummaryModel。"""
    model = create_summary_model(None)
    assert isinstance(model, DeterministicSummaryModel)


def test_llm_summary_model_falls_back_when_no_llm():
    """LlmSummaryModel 无 LLM 时降级为确定性版。"""
    model = LlmSummaryModel(None)
    result = AnalysisResult(analysis_id="t1", status="SUCCESS", conclusions=[{"text": "测试结论"}])
    response = model.compose(result)
    assert response["summary"] == "测试结论"


# ── Research Agent ──


def test_research_agent_factory_non_comprehensive_returns_rule_based():
    """非 comprehensive 类型返回规则版（快路径）。"""
    agent = create_research_agent(None, analysis_type="technical")
    assert isinstance(agent, RuleBasedResearchAgent)


def test_research_agent_factory_comprehensive_no_llm_returns_rule_based():
    """comprehensive 但无 LLM 时也降级为规则版。"""
    agent = create_research_agent(None, analysis_type="comprehensive")
    assert isinstance(agent, RuleBasedResearchAgent)


def test_rule_based_research_agent_selects_first_unfulfilled():
    """规则版选第一个未满足的需求。"""
    agent = RuleBasedResearchAgent()
    observations = [{"capability": "market.resolve_instrument", "status": "SUCCESS"}]
    requirements = [
        {"capability": "market.resolve_instrument", "arguments": {"symbol": "600519"}},
        {"capability": "market.get_realtime_quote", "arguments": {"symbol": "600519"}, "reason": "需要行情"},
    ]
    action = agent.choose_next_action(observations, requirements)
    assert action.action == "market.get_realtime_quote"
    assert not action.is_finish


def test_rule_based_research_agent_finishes_when_all_fulfilled():
    """所有需求满足时返回 finish。"""
    agent = RuleBasedResearchAgent()
    observations = [{"capability": "market.get_realtime_quote", "status": "SUCCESS"}]
    requirements = [{"capability": "market.get_realtime_quote", "arguments": {}}]
    action = agent.choose_next_action(observations, requirements)
    assert action.is_finish
