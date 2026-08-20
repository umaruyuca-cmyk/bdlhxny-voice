"""Direct response model 降级与工厂测试。"""

from __future__ import annotations

from bdlh_runtime.runtimes.langgraph.agents.direct_response_model import (
    DeterministicDirectResponseModel,
    LlmDirectResponseModel,
    create_direct_response_model,
)


def test_direct_response_factory_no_llm_returns_deterministic():
    model = create_direct_response_model(None)
    assert isinstance(model, DeterministicDirectResponseModel)


def test_deterministic_direct_response_answers_known_keyword():
    model = DeterministicDirectResponseModel()
    answer = model.answer("什么是市盈率？")
    assert "市盈率" in answer or "PE" in answer


def test_llm_direct_response_falls_back_on_error():
    class FakeLlm:
        def invoke(self, messages):
            raise RuntimeError("模拟 LLM 故障")

    model = LlmDirectResponseModel(FakeLlm())
    answer = model.answer("解释一下市净率")
    assert "市净率" in answer or "PB" in answer
