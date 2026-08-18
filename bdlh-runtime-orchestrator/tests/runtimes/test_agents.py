"""Agent LLM 实现与降级测试。

验证：无 LLM 时各 Agent 降级为规则版且行为正确；LLM 调用失败时也降级。
"""

from __future__ import annotations

from bdlh_runtime.contracts.analysis import AnalysisResult
from bdlh_runtime.runtimes.langgraph.agents.query_agent import (
    LlmUnderstandAgent,
    RuleBasedUnderstandAgent,
    create_understand_agent,
)
from bdlh_runtime.runtimes.langgraph.agents.research_agent import (
    RuleBasedResearchAgent,
    create_research_agent,
)
from bdlh_runtime.runtimes.langgraph.agents.summary_model import (
    DeterministicSummaryModel,
    LlmSummaryModel,
    create_summary_model,
)


# ── Query Agent ──


def test_query_agent_factory_no_llm_returns_rule_based():
    """无 LLM 时工厂返回 RuleBasedUnderstandAgent。"""
    agent = create_understand_agent(None)
    assert isinstance(agent, RuleBasedUnderstandAgent)


def test_llm_query_agent_falls_back_when_no_llm():
    """LlmUnderstandAgent 无 LLM 时降级为规则版行为。"""
    agent = LlmUnderstandAgent(None)
    output = agent.understand({"message": "分析 600519 技术面"})
    assert output.entities.instruments == ["600519"]
    assert output.needs_external is True


def test_llm_query_agent_falls_back_on_llm_error():
    """LLM 调用异常时降级为规则版，不抛错。"""

    class FakeLlm:
        def invoke(self, messages):
            raise RuntimeError("模拟 LLM 故障")

    agent = LlmUnderstandAgent(FakeLlm())
    output = agent.understand({"message": "600519 综合分析"})
    assert output.entities.instruments == ["600519"]
    assert output.needs_external is True


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


def test_research_agent_factory_no_llm_returns_rule_based():
    """重写：单一 Agent；无 LLM 返回规则版。"""
    agent = create_research_agent(None)
    assert isinstance(agent, RuleBasedResearchAgent)


def test_rule_based_research_agent_selects_first_unfulfilled():
    """规则版选第一个未满足的需求。"""
    agent = RuleBasedResearchAgent()
    observations = [{"capability": "market.resolve_instrument", "status": "SUCCESS"}]
    allowed_specs = [
        {"name": "market.resolve_instrument", "required_arguments": ["symbol"], "depends_on": []},
        {"name": "market.get_realtime_quote", "required_arguments": ["symbol"],
         "depends_on": ["market.resolve_instrument"]},
    ]
    action = agent.choose_next_action(observations, allowed_specs)
    assert action.action == "market.get_realtime_quote"
    assert not action.is_finish


def test_rule_based_research_agent_finishes_when_all_fulfilled():
    """所有需求满足时返回 finish。"""
    agent = RuleBasedResearchAgent()
    observations = [
        {"capability": "market.resolve_instrument", "status": "SUCCESS"},
        {"capability": "market.get_realtime_quote", "status": "SUCCESS"},
    ]
    allowed_specs = [
        {"name": "market.resolve_instrument", "required_arguments": ["symbol"], "depends_on": []},
        {"name": "market.get_realtime_quote", "required_arguments": ["symbol"],
         "depends_on": ["market.resolve_instrument"]},
    ]
    action = agent.choose_next_action(observations, allowed_specs)
    assert action.is_finish
