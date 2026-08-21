"""无需工具的知识问答模型。

该组件只负责回答不依赖实时数据的解释类问题，执行模式是一次受控 LLM 调用，
不是 ReAct Agent，也不允许调用 MCP、Java API 或其他 Tool。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger("bdlh_runtime.agents.direct_response")


class DirectResponseModel(Protocol):
    def answer(self, message: str) -> str:
        """根据用户问题返回自然语言回答。"""
        ...


class DeterministicDirectResponseModel:
    """无模型环境的可测试降级实现。"""

    _ANSWERS = {
        "市盈率": "市盈率（PE）是股票价格与每股收益的比值，常用于衡量市场为企业盈利支付的估值倍数。比较时应结合行业、盈利稳定性和增长预期，不能只看数值高低。",  # noqa: E501 —— 单条中文知识内容串，拆行反而破坏可读性
        "pe": "市盈率（PE）是股票价格与每股收益的比值，常用于衡量市场为企业盈利支付的估值倍数。比较时应结合行业、盈利稳定性和增长预期，不能只看数值高低。",  # noqa: E501 —— 单条中文知识内容串，拆行反而破坏可读性
        "市净率": "市净率（PB）是股票价格与每股净资产的比值，常用于观察市场相对账面净资产给出的估值。它更适合与同行业公司及企业自身历史区间比较。",  # noqa: E501 —— 单条中文知识内容串，拆行反而破坏可读性
        "pb": "市净率（PB）是股票价格与每股净资产的比值，常用于观察市场相对账面净资产给出的估值。它更适合与同行业公司及企业自身历史区间比较。",  # noqa: E501 —— 单条中文知识内容串，拆行反而破坏可读性
    }

    def answer(self, message: str) -> str:
        normalized = message.strip().lower()
        for keyword, answer in self._ANSWERS.items():
            if keyword in normalized:
                return answer
        return f"关于“{message.strip()}”：当前未配置可用的大模型，暂时只能提供基础说明。"


_SYSTEM_PROMPT = (
    "你是 BDLH Agent Runtime 助手。用清晰、克制的中文直接回答用户问题。"
    "本次是单次直接模型调用，不可调用任何工具；不得虚构实时行情、财务数字、"
    "用户未提供的账户或持仓信息。"
    "若问题明显需要实时数据或深度研究类能力，可说明当前是普通对话，"
    "用户可在需要时自行启用对应插件后再试——不要默认把自己说成金融分析系统。"
)


class LlmDirectResponseModel:
    """一次 LLM 调用模式；失败时确定性降级，不执行 Tool Loop。"""

    def __init__(self, llm: Any):
        self._llm = llm
        self._fallback = DeterministicDirectResponseModel()

    def answer(self, message: str) -> str:
        try:
            response = self._llm.invoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ]
            )
            content = response.content if hasattr(response, "content") else str(response)
            normalized = str(content).strip()
            return normalized or self._fallback.answer(message)
        except Exception as exc:
            logger.warning("直接问答模型调用失败，使用确定性回答: %s", exc)
            return self._fallback.answer(message)


def create_direct_response_model(llm: Any | None) -> DirectResponseModel:
    if llm is None:
        return DeterministicDirectResponseModel()
    return LlmDirectResponseModel(llm)
