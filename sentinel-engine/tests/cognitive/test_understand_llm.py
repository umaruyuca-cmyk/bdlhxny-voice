"""LLM Understand：契约解析、走私拒绝、失败软澄清。"""

from __future__ import annotations

import json

import pytest

from bdlh_runtime.cognitive.understand import (
    LlmUnderstandModel,
    create_understand_model,
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
async def test_llm_understand_rejects_route_and_soft_fails() -> None:
    model = LlmUnderstandModel(_FakeSmuggleLlm())
    out = await model.understand("600519 新闻")
    assert out.action is None
    assert out.needs_external is False
    assert out.reason_codes == []


@pytest.mark.asyncio
async def test_llm_understand_soft_fails_on_bad_json() -> None:
    model = LlmUnderstandModel(_FakeBadJsonLlm())
    out = await model.understand("什么是市盈率")
    assert out.action is None
    assert out.needs_external is False


@pytest.mark.asyncio
async def test_llm_understand_rejects_capability_name_in_objective() -> None:
    model = LlmUnderstandModel(
        _FakeCapabilityInObjectiveLlm(),
        capability_names=("market.data.get_quote",),
    )
    out = await model.understand("看行情")
    assert out.action is None
    assert out.needs_external is False
    assert out.reason_codes == ["UNDERSTAND_CAPABILITY_SMUGGLED"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "objective",
    ["分析 Node.js 生态公司", "查看 v1.2 版本更新", "收益率约 3.5%"],
)
async def test_llm_understand_allows_dotted_natural_language(objective: str) -> None:
    payload = _valid_payload()
    payload["goals"][0]["objective"] = objective
    model = LlmUnderstandModel(
        _CapturingLlm(payload),
        capability_names=("research.deep_search", "market.data.get_quote"),
    )
    out = await model.understand("随便问一句")
    assert out.needs_external is True
    assert out.goals[0].objective == objective


@pytest.mark.asyncio
async def test_llm_understand_rejects_registered_capability_token() -> None:
    payload = _valid_payload()
    payload["goals"][0]["objective"] = "先调用 research.deep_search"
    model = LlmUnderstandModel(
        _CapturingLlm(payload),
        capability_names=("research.deep_search",),
    )
    out = await model.understand("看行情")
    assert out.needs_external is False
    assert out.action is None
    assert out.reason_codes == ["UNDERSTAND_CAPABILITY_SMUGGLED"]


def test_create_understand_model_without_llm_raises() -> None:
    from bdlh_runtime.infra.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="Understand 需要 LLM"):
        create_understand_model(None)


class _CapturingLlm:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.messages: list[list[dict]] = []

    async def ainvoke(self, messages: list[dict]) -> object:
        self.messages.append(messages)
        return type("R", (), {"content": json.dumps(self.payload, ensure_ascii=False)})()


def _valid_payload(**overrides: object) -> dict:
    payload = {
        "goals": [
            {
                "goal_id": "g1",
                "objective": "解读 600519 近期新闻影响",
                "requested_topics": ["news"],
                "needs_account": False,
                "needs_profile": False,
                "success_criteria": [{"criterion_id": "c1", "topic": "news", "description": "覆盖新闻主题"}],
            }
        ],
        "entities": {"instruments": ["600519"], "time_range": None},
        "constraints": [],
        "missing": [],
        "needs_external": True,
        "action": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_llm_understand_keeps_action_only_when_enabled() -> None:
    llm = _CapturingLlm(_valid_payload(action={"tool": "finance.stock-research", "parameters": {"symbol": "600519"}}))
    model = LlmUnderstandModel(llm)
    enabled = await model.understand(
        "600519 最近有什么新闻",
        enabled_skills=frozenset({"finance.stock-research"}),
    )
    assert enabled.action is not None
    assert enabled.action.tool == "finance.stock-research"
    assert enabled.action.parameters == {"symbol": "600519"}
    assert "finance.stock-research" in llm.messages[0][1]["content"]

    disabled = await model.understand("600519 最近有什么新闻", enabled_skills=frozenset())
    assert disabled.action is None
    assert "本轮没有可用工具" in llm.messages[1][1]["content"]
