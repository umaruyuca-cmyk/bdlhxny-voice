"""Mem0 记忆实现。

Mem0 内部会用 LLM 做"抽取要点 + 去重更新 + 重排"三件事，记忆质量优于裸
向量化。但这些内部调用带来额外开销和故障面，因此本实现严格遵循架构文档
v3.1 §5.4 的工程约束：

1. 内部 LLM 显式配 DeepSeek，不用 Mem0 默认 OpenAI（避免未声明依赖）；
2. Embedding 显式配 Qwen3；
3. 所有操作 try-except，失败时降级为空结果，绝不抛致命异常；
4. search/add 耗时由调用方计入运行预算。

Mem0 后端（PG + pgvector + Qwen3 Embedding 服务）尚未部署时，工厂函数
create_memory_store 会自动回退到 NoOpMemoryStore。
"""

from __future__ import annotations

import logging
from typing import Any

from ..base import MemoryRecord, MemoryStore, UserProfile
from ..noop import NoOpMemoryStore

logger = logging.getLogger("stockwise_analysis.memory.mem0")


class Mem0MemoryStore:
    """基于 Mem0 的记忆存储实现。

    Mem0 客户端在 __init__ 时初始化；若初始化失败（缺依赖、后端不可达），
    由工厂函数降级为 NoOpMemoryStore，调用方不感知。
    """

    def __init__(self, mem0_client: Any, profile_store: Any = None):
        """注入已初始化的 Mem0 client 和可选的画像存储。

        profile_store 负责读写结构化 UserProfile（PG 表），与 Mem0 的语义
        记忆分离——画像走确定性查询，不走向量召回。
        """
        self._client = mem0_client
        self._profile_store = profile_store

    async def search(self, query: str, user_id: str, *, limit: int = 5) -> list[MemoryRecord]:
        """语义召回相关记忆。Mem0 失败时返回空列表（降级语义）。"""
        try:
            results = self._client.search(query=query, user_id=user_id, limit=limit)
            # Mem0 返回格式：list[dict]，每条含 memory/score/user_id 等
            return [
                MemoryRecord(
                    content=item.get("memory", item.get("content", "")),
                    score=float(item.get("score", 0.0)),
                    metadata={k: v for k, v in item.items() if k not in ("memory", "content", "score")},
                )
                for item in (results or [])
            ]
        except Exception as exc:
            logger.warning("Mem0 search 降级返回空 (user_id=%s): %s", user_id, exc)
            return []

    async def get_profile(self, user_id: str) -> UserProfile | None:
        """读取用户结构化画像。profile_store 失败或无画像时返回 None。"""
        if self._profile_store is None:
            return None
        try:
            return self._profile_store.get_profile(user_id)
        except Exception as exc:
            logger.warning("画像读取降级返回 None (user_id=%s): %s", user_id, exc)
            return None

    async def add(self, content: str, user_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        """沉淀记忆。Mem0 内部会抽取要点并去重。失败时仅记日志不抛异常。"""
        try:
            self._client.add(content, user_id=user_id, metadata=metadata or {})
        except Exception as exc:
            logger.warning("Mem0 add 失败已忽略 (user_id=%s): %s", user_id, exc)


def create_memory_store(
    *,
    mem0_llm_model: str,
    mem0_llm_api_key: str | None,
    mem0_llm_base_url: str,
    mem0_embedder_model: str,
    mem0_embedder_api_key: str | None,
    mem0_embedder_base_url: str | None,
    profile_store: Any = None,
) -> MemoryStore:
    """工厂函数：尝试初始化 Mem0，失败则降级为 NoOp。

    Mem0 的初始化涉及 LLM/Embedding 配置注入和后端连接探测，任何一步失败
    都意味着记忆层暂不可用——此时返回 NoOpMemoryStore，主流程继续跑。
    调用方（Application Runtime）应在启动时调用一次，缓存返回的实例。
    """
    try:
        # 延迟导入：Mem0 是可选依赖，未安装时直接降级
        from mem0 import Memory  # type: ignore[import-not-found]

        config: dict[str, Any] = {
            "llm": {
                "provider": "openai",  # Mem0 用 OpenAI 兼容接口接 DeepSeek
                "config": {
                    "model": mem0_llm_model,
                    "api_key": mem0_llm_api_key or "",
                    "openai_base_url": mem0_llm_base_url,
                },
            },
        }
        # Embedding 配置：有 base_url 时走自定义，否则让 Mem0 用默认（不推荐）
        if mem0_embedder_base_url:
            config["embedder"] = {
                "provider": "openai",  # 同样用兼容接口接 Qwen3
                "config": {
                    "model": mem0_embedder_model,
                    "api_key": mem0_embedder_api_key or "",
                    "openai_base_url": mem0_embedder_base_url,
                },
            }

        client = Memory.from_config(config)
        logger.info("Mem0 记忆层初始化成功 (llm=%s, embedder=%s)", mem0_llm_model, mem0_embedder_model)
        return Mem0MemoryStore(client, profile_store=profile_store)

    except ImportError:
        logger.info("mem0 包未安装，记忆层降级为 NoOp")
        return NoOpMemoryStore()
    except Exception as exc:
        logger.warning("Mem0 初始化失败，记忆层降级为 NoOp: %s", exc)
        return NoOpMemoryStore()
