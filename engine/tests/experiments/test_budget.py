"""作业级费用硬限额(修复方案 §11.2)测试:累计、超限判定、预算终止行为。"""

from __future__ import annotations

import pytest

from bdlh_runtime.experiments.budget import JobBudget


def test_unlimited_budget_never_exhausts():
    budget = JobBudget()
    budget.record(llm_requests=10_000, input_tokens=10**9, cost=999.0)
    assert not budget.exhausted
    assert budget.terminated_reason == ""


def test_llm_request_limit_triggers():
    budget = JobBudget(max_llm_requests=8)
    budget.record(llm_requests=4)
    assert not budget.exhausted
    budget.record(llm_requests=5)
    assert budget.exhausted
    assert "MAX_LLM_REQUESTS_PER_JOB" in budget.terminated_reason


def test_token_and_cost_limits_trigger():
    tokens = JobBudget(max_input_tokens=1000)
    tokens.record(input_tokens=600)
    tokens.record(input_tokens=600)
    assert "MAX_INPUT_TOKENS_PER_JOB" in tokens.terminated_reason

    cost = JobBudget(max_estimated_cost=1.0)
    cost.record(cost=0.6)
    cost.record(cost=0.6)
    assert "MAX_ESTIMATED_COST_PER_JOB" in cost.terminated_reason


def test_first_reason_wins_and_payload_reflects():
    budget = JobBudget(max_llm_requests=1, max_input_tokens=10)
    budget.record(llm_requests=5, input_tokens=500)
    payload = budget.to_payload()
    assert payload["terminated_reason"] == budget.terminated_reason
    assert payload["llm_requests"] == 5
    assert payload["limits"]["max_llm_requests"] == 1


def test_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_LLM_REQUESTS_PER_JOB", "20")
    monkeypatch.setenv("MAX_INPUT_TOKENS_PER_JOB", "50000")
    monkeypatch.setenv("MAX_ESTIMATED_COST_PER_JOB", "2.5")
    budget = JobBudget.from_env()
    assert (budget.max_llm_requests, budget.max_input_tokens, budget.max_estimated_cost) == (20, 50000, 2.5)
