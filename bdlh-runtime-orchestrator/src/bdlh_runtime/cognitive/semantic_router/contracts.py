"""语义路由契约。

路由名是内核快路径（闲聊 / 知识 / 禁止），不是 Domain 或 Skill 标识。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RouteDisposition(StrEnum):
    """命中后的处置；未命中不走本枚举，路由器返回 None。"""

    RESPOND = "RESPOND"
    BLOCK = "BLOCK"


class Route(BaseModel):
    """一条语义路由：用示例话语划定向量区域，用阈值决定是否触发。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    utterances: tuple[str, ...] = Field(min_length=1)
    score_threshold: float = Field(default=0.42, ge=0.0, le=1.0)
    disposition: RouteDisposition = RouteDisposition.RESPOND
    response: str | None = None


class RouteChoice(BaseModel):
    """一次路由决策。``None`` 表示应进入 Understand / Agent，而不是本对象。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    similarity: float = Field(ge=0.0, le=1.0)
    disposition: RouteDisposition
    response: str | None = None
    scores: dict[str, float] = Field(default_factory=dict)
