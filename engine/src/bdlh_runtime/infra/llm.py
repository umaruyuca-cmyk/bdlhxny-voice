"""大模型客户端封装。

本项目通过 langchain-openai 的 ChatOpenAI 接入 OpenAI 兼容接口。
端点与模型配置的唯一真源是服务端环境变量(``deploy/.env`` / compose /
云 secret 注入 → ``LLM_BASE_URL`` / ``LLM_MODEL``),代码不内置默认端点:
``LLM_BASE_URL`` 缺失视为配置错误,``create_llm`` 返回 None 并在日志说明,
由调用方降级或明确报错——绝不静默改用其他端点。

降级策略：没有 API Key 或没有 base_url 时 create_llm 返回 None，调用方据此降级为规则替身。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("bdlh_runtime.infra.llm")

DEFAULT_LLM_MODEL = "Qwen/Qwen3.6-35B-A3B"


def create_llm(
    *,
    api_key: str | None,
    base_url: str | None = None,
    model: str = DEFAULT_LLM_MODEL,
    temperature: float = 0.1,
    timeout: float = 30.0,
) -> Any | None:
    """创建 ChatOpenAI 实例（OpenAI 兼容）。

    ``base_url`` 解析顺序:显式参数 → 环境变量 ``LLM_BASE_URL``。
    两者都缺失时不再回退到内置端点(env 是唯一真源)。

    返回 None 的情况：
    - api_key 为空（未配置 LLM_API_KEY）；
    - base_url 为空（未配置 LLM_BASE_URL,且调用方未显式传入）;
    - langchain_openai 未安装。

    调用方拿到 None 时应降级为规则替身或明确报错，不要把 None 当错误处理。

    temperature 默认 0.1：对照评测要求输出可复现，降低随机性。
    """

    if not api_key:
        logger.info("未配置 LLM_API_KEY，LLM 降级为规则替身")
        return None

    resolved_base_url = (base_url or os.getenv("LLM_BASE_URL") or "").strip()
    if not resolved_base_url:
        logger.info("未配置 LLM_BASE_URL(env 是唯一配置来源,无内置默认端点)，LLM 降级为规则替身")
        return None

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.warning("langchain-openai 未安装，LLM 降级为规则替身")
        return None

    logger.info("LLM 初始化成功 (model=%s, base_url=%s)", model, resolved_base_url)
    return ChatOpenAI(
        api_key=api_key,
        base_url=resolved_base_url,
        model=model,
        temperature=temperature,
        timeout=timeout,
    )
