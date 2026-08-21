"""LLM Understand：契约解析、走私拒绝、失败降级。"""

from __future__ import annotations

import json

import pytest

from bdlh_runtime.cognitive.understand import (
    LlmUnderstandModel,
    RuleBasedUnderstandModel,
    create_understand_model,
    rule_based_understand,
)


class _FakeOkLlm:
    async def ainvoke(self, messages: list[dict]) -> object:
        del messages
        payload = {
            "goals": [
                {
                    "goal_id": "g1",
                    "objective": "解读 600519 近期新闻影响",
                    "requested_topics": ["news"],
                    "needs_account": False,
                    "needs_profile": False,
                    "success_criteria": [
                        {
                            "criterion_id": "c1",
                            "topic": "news",
                            "description": "覆盖新闻主题",
                        }
                    ],
                }
            ],
            "entities": {"instruments": ["600519"], "time_range": None},
            "constraints": [],
            "missing": [],
            "needs_external": True,
        }
        return type("R", (), {"content": json.dumps(payload, ensure_ascii=False)})()


class _FakeSmuggleLlm:
    async def ainvoke(self, messages: list[dict]) -> object:
        del messages
        payload = {
            "goals": [
                {
                    "goal_id": "g1",
                    "objective": "研究标的",
                    "success_criteria": [{"criterion_id": "c1", "description": "完成研究"}],
                }
            ],
            "route": "finance.research",
            "needs_external": True,
        }
        return type("R", (), {"content": json.dumps(payload)})()


class _FakeBadJsonLlm:
    async def ainvoke(self, messages: list[dict]) -> object:
        del messages
        return type("R", (), {"content": "not-json"})()


class _FakeCapabilityInObjectiveLlm:
    async def ainvoke(self, messages: list[dict]) -> object:
        del messages
        payload = {
            "goals": [
                {
                    "goal_id": "g1",
                    "objective": "调用 market.data.get_quote",
                    "success_criteria": [{"criterion_id": "c1", "description": "拿到报价"}],
                }
            ],
            "needs_external": True,
        }
        return type("R", (), {"content": json.dumps(payload)})()


@pytest.mark.asyncio
async def test_llm_understand_parses_valid_json() -> None:
    model = LlmUnderstandModel(_FakeOkLlm())
    out = await model.understand("600519 最近有什么新闻")
    assert out.needs_external is True
    assert out.entities.instruments == ["600519"]
    assert out.goals[0].requested_topics == ["news"]
    assert out.goals[0].status == "PENDING"
    assert out.goals[0].success_criteria[0].candidate_capabilities == []


@pytest.mark.asyncio
async def test_llm_understand_rejects_route_and_falls_back() -> None:
    model = LlmUnderstandModel(_FakeSmuggleLlm())
    out = await model.understand("600519 新闻")
    fallback = rule_based_understand("600519 新闻")
    assert out.model_dump() == fallback.model_dump()


@pytest.mark.asyncio
async def test_llm_understand_falls_back_on_bad_json() -> None:
    model = LlmUnderstandModel(_FakeBadJsonLlm())
    out = await model.understand("什么是市盈率")
    assert out.needs_external is False
    assert out.goals[0].objective.startswith("解释概念")


@pytest.mark.asyncio
async def test_llm_understand_rejects_capability_name_in_objective() -> None:
    model = LlmUnderstandModel(_FakeCapabilityInObjectiveLlm())
    out = await model.understand("看行情")
    assert out == await RuleBasedUnderstandModel().understand("看行情")


def test_create_understand_model_without_llm_is_rule_based() -> None:
    model = create_understand_model(None)
    assert isinstance(model, RuleBasedUnderstandModel)
