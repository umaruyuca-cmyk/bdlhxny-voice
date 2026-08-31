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
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

logger = logging.getLogger("bdlh_runtime.infra.llm")

DEFAULT_LLM_MODEL = "Qwen/Qwen3.6-35B-A3B"


@dataclass(frozen=True)
class ModelCapability:
    """模型适配器的能力描述(混合路线阶段 A2)。

    - ``supports_*``:模型+适配器是否接受该参数(适配器不传递即视为不支持);
    - ``*_note``:普通语言原因;参数被拒绝/删除/改写时进入 unsupported_reasons;
    - Fake 模型通过 ``model_capabilities`` 属性模拟支持/不支持两种情况,
      仅仅从环境变量复制到 effective 不算生效确认。
    """

    supports_temperature: bool = True
    temperature_note: str = "适配器把 temperature 传给 SDK,请求值确认为生效值"
    supports_top_p: bool = False
    top_p_note: str = "适配器当前不向 SDK 传递 top_p,请求值不能记为已生效"
    supports_reasoning_effort: bool = False
    reasoning_effort_note: str = "适配器当前不向 SDK 传递 reasoning_effort,请求值不能记为已生效"
    supports_seed: bool = False
    seed_note: str = "适配器当前不向 SDK 传递 seed,请求值不能记为已生效"
    supports_max_output_tokens: bool = True
    max_output_tokens_note: str = "适配器把 max_tokens 传给 SDK,配置值确认为生效值"
    supports_parallel_tool_calls: bool = True
    parallel_tool_calls_note: str = "适配器经 model_kwargs 把 parallel_tool_calls 传给 SDK,配置值确认为生效值"
    supports_tool_choice: bool = False
    tool_choice_note: str = "适配器当前不向 SDK 传递 tool_choice,由模型自行决定"

    def as_payload(self) -> dict[str, Any]:
        return {
            "supports_temperature": self.supports_temperature,
            "supports_top_p": self.supports_top_p,
            "supports_reasoning_effort": self.supports_reasoning_effort,
            "supports_seed": self.supports_seed,
            "supports_max_output_tokens": self.supports_max_output_tokens,
            "supports_parallel_tool_calls": self.supports_parallel_tool_calls,
            "supports_tool_choice": self.supports_tool_choice,
        }


def adapter_default_capability() -> ModelCapability:
    """create_llm 适配器实际传给 SDK 的参数口径。

    ChatOpenAI 构造传递 temperature/max_tokens,parallel_tool_calls 经
    model_kwargs 逐请求传递;top_p、reasoning_effort、seed、tool_choice
    未进入构造参数——按「未传递即不支持」保守声明,避免把环境变量
    复制值冒充生效值。
    """
    return ModelCapability()


def capabilities_of(llm: Any) -> ModelCapability:
    """读取模型客户端的能力描述。

    - Fake/测试模型:设置 ``llm.model_capabilities``(ModelCapability 或 dict)
      即可模拟支持/不支持两种情况;
    - langchain ChatOpenAI:使用适配器保守口径(只声明确实传递的参数);
    - 其他未知实现:全部不支持(保守,fail-closed)。
    """
    declared = getattr(llm, "model_capabilities", None)
    if isinstance(declared, ModelCapability):
        return declared
    if isinstance(declared, Mapping):
        return replace(
            adapter_default_capability(),
            **{key: bool(value) for key, value in declared.items() if key in ModelCapability.__dataclass_fields__},
        )
    if llm is None:
        return replace(
            adapter_default_capability(),
            supports_temperature=False,
            temperature_note="LLM 未配置(create_llm 返回 None),无生效值可言",
        )
    class_path = f"{type(llm).__module__}.{type(llm).__qualname__}"
    if class_path.startswith("langchain_openai") or type(llm).__name__ == "ChatOpenAI":
        return adapter_default_capability()
    return replace(
        adapter_default_capability(),
        supports_temperature=False,
        temperature_note="未知模型实现,适配器无法确认 temperature 已生效",
        supports_max_output_tokens=False,
        max_output_tokens_note="未知模型实现,适配器无法确认 max_output_tokens 已生效",
        supports_parallel_tool_calls=False,
        parallel_tool_calls_note="未知模型实现,适配器无法确认 parallel_tool_calls 已生效",
    )


def create_llm(
    *,
    api_key: str | None,
    base_url: str | None = None,
    model: str = DEFAULT_LLM_MODEL,
    temperature: float = 0.1,
    timeout: float = 30.0,
    max_output_tokens: int | None = None,
    parallel_tool_calls: bool | None = None,
    max_retries: int | None = None,
) -> Any | None:
    """创建 ChatOpenAI 实例（OpenAI 兼容）。

    ``base_url`` 解析顺序:显式参数 → 环境变量 ``LLM_BASE_URL``。
    两者都缺失时不再回退到内置端点(env 是唯一真源)。

    返回 None 的情况：
    - api_key 为空（未配置 LLM_API_KEY）；
    - base_url 为空（未配置 LLM_BASE_URL,且调用方未显式传入);
    - langchain_openai 未安装。

    调用方拿到 None 时应降级为规则替身或明确报错，不要把 None 当错误处理。

    temperature 默认 0.1：对照评测要求输出可复现，降低随机性。
    ``max_output_tokens``/``parallel_tool_calls``/``max_retries`` 为 None 时
    不向 SDK 传递 (保持端点默认);显式给出才进入构造参数——保证配置里
    记录的冻结条件与实际发给 SDK 的参数一致。SDK 默认 max_retries=2 会把
    一次超时放大成 3 倍墙钟时间,对有降级兜底的调用方应显式传 0。
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
    extra: dict[str, Any] = {}
    if max_output_tokens is not None:
        extra["max_tokens"] = int(max_output_tokens)
    if parallel_tool_calls is not None:
        # ChatOpenAI 把非默认参数转存 model_kwargs,随每个请求发送
        extra["model_kwargs"] = {"parallel_tool_calls": bool(parallel_tool_calls)}
    if max_retries is not None:
        extra["max_retries"] = int(max_retries)
    return ChatOpenAI(
        api_key=api_key,
        base_url=resolved_base_url,
        model=model,
        temperature=temperature,
        timeout=timeout,
        **extra,
    )
