"""HTTP API 输入输出契约。

HTTP 层只负责请求校验和响应序列化；业务状态结构由 graph/state.py 管理。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """创建一次股票分析运行的请求。"""

    message: str
    symbol: str | None = None
    user_id: str | None = None
    require_confirmation: bool = False
    scope: str | None = None


class ResumeRequest(BaseModel):
    """恢复 interrupt() 暂停流程时由用户补充的内容。"""

    value: dict[str, Any] | str


class RunResponse(BaseModel):
    """对外暴露的运行快照；不返回完整内部 State。"""

    run_id: str
    status: str
    next_stage: str | None = None
    final_response: dict[str, Any] | None = None
    interrupts: list[Any] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
