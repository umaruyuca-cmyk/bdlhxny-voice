"""HTTP API 输入输出契约。

HTTP 层只负责请求校验和响应序列化；业务状态结构由 graph/state.py 管理。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """创建一次股票分析运行的请求。"""

    message: str
    symbol: str | None = None
    # 仅供无鉴权的本地测试；启用 JWT 后必须与 Token subject 一致，不能作为身份来源。
    user_id: str | None = None
    thread_id: str | None = None  # v2.1 P0-7：传入则延续已有会话，否则新建
    require_confirmation: bool = False
    scope: str | None = None


class ResumeRequest(BaseModel):
    """恢复 interrupt() 暂停流程时由用户补充的内容。"""

    value: dict[str, Any] | str


class ChatRequest(BaseModel):
    """统一聊天页面请求；用户身份只来自 JWT，mode 不参与业务路由。"""

    session_id: str | None = Field(default=None, alias="sessionId", max_length=128)
    mode: str = Field(default="general", max_length=32)
    message: str = Field(min_length=1, max_length=20_000)
    instrument: dict[str, Any] | None = None
    regenerate: bool = False


class RunResponse(BaseModel):
    """对外暴露的运行快照；不返回完整内部 State。"""

    run_id: str
    thread_id: str | None = None
    status: str
    next_stage: str | None = None
    final_response: dict[str, Any] | None = None
    interrupts: list[Any] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)


class CreateFinancialTaskRequest(BaseModel):
    """创建首个 M6 价格观察任务；身份始终来自 JWT。"""

    symbol: str = Field(pattern=r"^\d{6}$")
    market: Literal["CN"] = "CN"
    instrument_name: str | None = Field(default=None, max_length=128)
    direction: Literal["AT_OR_ABOVE", "AT_OR_BELOW"]
    threshold: float = Field(gt=0, allow_inf_nan=False)
    currency: Literal["CNY"] = "CNY"
    cadence_seconds: int = Field(default=300, ge=60, le=86_400)
    first_wakeup_at: datetime | None = None
    expires_at: datetime
    confirmed: Literal[True]
