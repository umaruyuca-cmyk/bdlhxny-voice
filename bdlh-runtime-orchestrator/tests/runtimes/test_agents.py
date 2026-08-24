"""Direct response model 失败文案与工厂测试。"""

from __future__ import annotations

import pytest

from bdlh_runtime.runtime.errors import ConfigurationError
from bdlh_runtime.runtimes.langgraph.agents.direct_response_model import (
    LlmDirectResponseModel,
    create_direct_response_model,
)
from tests.helpers_direct_response import DeterministicDirectResponseModel


def test_direct_response_factory_no_llm_raises():
    with pytest.raises(ConfigurationError, match="Direct response 需要 LLM"):
        create_direct_response_model(None)


def test_deterministic_direct_response_answers_known_keyword():
    model = DeterministicDirectResponseModel()
    answer = model.answer("什么是市盈率？")
    assert "市盈率" in answer or "PE" in answer


def test_llm_direct_response_returns_failure_message_on_error():
    class FakeLlm:
        def invoke(self, messages):
            raise RuntimeError("模拟 LLM 故障")

    model = LlmDirectResponseModel(FakeLlm())
    answer = model.answer("解释一下市净率")
    assert answer == "暂时无法完成回答，请稍后重试"
