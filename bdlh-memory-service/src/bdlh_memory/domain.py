from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class MemoryRecord(BaseModel):
    memory_id: str | None = None
    content: str = Field(min_length=1, max_length=1200)
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)


class MemoryCandidate(BaseModel):
    event_id: UUID
    authenticated_user_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=1200)
    metadata: dict[str, Any]

    @field_validator("content")
    @classmethod
    def reject_conversation_and_secrets(cls, value: str) -> str:
        text = value.strip()
        forbidden = ("authorization:", "bearer ", "api_key", "password=", "<conversation")
        if not text or any(token in text.lower() for token in forbidden):
            raise ValueError("memory candidate content is not permitted")
        return text

    def policy_allowed(self) -> bool:
        kind = str(self.metadata.get("knowledge_type", ""))
        return kind == "confirmed" and not any(
            key in self.metadata for key in ("risk_tolerance", "portfolio", "account", "checkpoint")
        )
