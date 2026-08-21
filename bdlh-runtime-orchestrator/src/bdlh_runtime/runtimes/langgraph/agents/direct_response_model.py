"""无需工具的知识问答模型。

该组件只负责回答不依赖实时数据的解释类问题，执行模式是一次受控 LLM 调用，
不是 ReAct Agent，也不允许调用 MCP、Java API 或其他 Tool。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger("bdlh_runtime.agents.direct_response")

_FAILURE_MESSAGE = "暂时无法完成回答，请稍后重试"


class DirectResponseModel(Protocol):
    def answer(self, message: str) -> str:
        """根据用户问题返回自然语言回答。"""
        ...


_SYSTEM_PROMPT = (
    "你是 BDLH Agent Runtime 助手。用清晰、克制的中文直接回答用户问题。"
    "本次是单次直接模型调用，不可调用任何工具；不得虚构实时行情、财务数字、"
    "用户未提供的账户或持仓信息。"
    "若问题明显需要实时数据或深度研究类能力，可说明当前是普通对话，"
    "用户可在需要时自行启用对应插件后再试——不要默认把自己说成金融分析系统。"
)


class LlmDirectResponseModel:
    """一次 LLM 调用模式；失败时返回短失败文案，不假装词典知识。"""

    def __init__(self, llm: Any):
        self._llm = llm

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
            if normalized:
                return normalized
            logger.warning("直接问答模型返回空内容")
            return _FAILURE_MESSAGE
        except Exception as exc:
            logger.warning("直接问答模型调用失败: %s", exc)
            return _FAILURE_MESSAGE


def create_direct_response_model(llm: Any) -> DirectResponseModel:
    """装配直接问答模型：产品路径必须有 LLM。"""
    if llm is None:
        from bdlh_runtime.runtime.errors import ConfigurationError

        raise ConfigurationError("Direct response 需要 LLM；产品路径不允许确定性替身装配")
    return LlmDirectResponseModel(llm)
