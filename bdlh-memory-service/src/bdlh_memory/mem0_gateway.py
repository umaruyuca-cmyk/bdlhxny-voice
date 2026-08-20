from __future__ import annotations

import asyncio
import json
from typing import Any

from .config import Settings
from .domain import MemoryRecord


class Mem0Gateway:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def search(self, user_id: str, query: str, top_k: int) -> list[MemoryRecord]:
        rows = await asyncio.to_thread(self._client.search, query=query, user_id=user_id, limit=top_k)
        return [MemoryRecord(
            memory_id=str(item.get("id")) if item.get("id") else None,
            content=str(item.get("memory") or item.get("content") or ""),
            score=float(item.get("score", 0.0)),
            metadata={k: v for k, v in item.items() if k not in {"id", "memory", "content", "score"}},
        ) for item in rows or [] if item.get("memory") or item.get("content")]

    async def add(self, user_id: str, content: str, metadata: dict[str, Any]) -> None:
        await asyncio.to_thread(self._client.add, content, user_id=user_id, metadata=metadata)

    async def get(self, memory_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._client.get, memory_id)

    async def delete(self, memory_id: str) -> None:
        await asyncio.to_thread(self._client.delete, memory_id)

    async def delete_user(self, user_id: str) -> None:
        await asyncio.to_thread(self._client.delete_all, user_id=user_id)


def create_gateway(settings: Settings) -> Mem0Gateway:
    from mem0 import Memory

    config: dict[str, Any] = {"llm": {"provider": "openai", "config": {
        "model": settings.mem0_llm_model, "api_key": settings.mem0_llm_api_key or "",
        "openai_base_url": settings.mem0_llm_base_url,
    }}}
    if settings.mem0_embedder_base_url:
        config["embedder"] = {"provider": "openai", "config": {
            "model": settings.mem0_embedder_model, "api_key": settings.mem0_embedder_api_key or "",
            "openai_base_url": settings.mem0_embedder_base_url,
        }}
    if settings.mem0_config_json:
        try:
            supplied = json.loads(settings.mem0_config_json)
        except json.JSONDecodeError as exc:
            raise ValueError("MEM0_CONFIG_JSON must be a JSON object") from exc
        if not isinstance(supplied, dict):
            raise ValueError("MEM0_CONFIG_JSON must be a JSON object")
        _deep_merge(config, supplied)
    elif settings.environment == "production":
        raise ValueError(
            "MEM0_CONFIG_JSON is required in production and must configure the memory-schema pgvector store"
        )
    return Mem0Gateway(Memory.from_config(config))


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


class UnavailableMem0Gateway:
    async def search(self, user_id: str, query: str, top_k: int) -> list[MemoryRecord]:
        del user_id, query, top_k
        return []

    async def add(self, user_id: str, content: str, metadata: dict[str, Any]) -> None:
        del user_id, content, metadata
        raise RuntimeError("Mem0 is unavailable")

    async def get(self, memory_id: str) -> dict[str, Any] | None:
        del memory_id
        return None

    async def delete(self, memory_id: str) -> None:
        del memory_id

    async def delete_user(self, user_id: str) -> None:
        del user_id
