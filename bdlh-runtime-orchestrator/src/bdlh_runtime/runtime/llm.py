"""大模型客户端封装。

本项目通过 langchain-openai 的 ChatOpenAI 接入 DeepSeek（OpenAI 兼容接口）。
所有需要 LLM 的 Agent（Query/Summary/Research）都通过本模块获取客户端实例，
不在各自模块里重复初始化——保证模型配置集中管理、可替换。

降级策略：没有 API Key 时 create_llm 返回 None，调用方据此降级为规则替身。
这与 Mem0 的降级思路一致：外部依赖不可用时主流程照跑，只是质量从 LLM 降到规则。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("bdlh_runtime.runtime.llm")


def create_llm(
    *,
    api_key: str | None,
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
    temperature: float = 0.1,
    timeout: float = 30.0,
) -> Any | None:
    """创建 ChatOpenAI 实例（指向 DeepSeek）。

    返回 None 的情况：
    - api_key 为空（未配置 DEEPSEEK_API_KEY）；
    - langchain_openai 未安装。

    调用方拿到 None 时应降级为规则替身（如 RuleBasedQueryAgent），
    不要把 None 当错误处理——这是设计内的降级路径。

    temperature 默认 0.1：金融分析场景需要确定性，降低随机性。
    """

    if not api_key:
        logger.info("未配置 DEEPSEEK_API_KEY，LLM 降级为规则替身")
        return None

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.warning("langchain-openai 未安装，LLM 降级为规则替身")
        return None

    logger.info("LLM 初始化成功 (model=%s, base_url=%s)", model, base_url)
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        timeout=timeout,
    )
