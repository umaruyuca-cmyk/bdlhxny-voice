"""HTTP API 输入输出契约。

HTTP 层只负责请求校验和响应序列化。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

#: 会话级 Skill id（Registry 裸 id 或「域.id」形式，如 finance.stock-research）
_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class RunRequest(BaseModel):
    """创建一次 Cognitive 运行的请求。"""

    message: str
    # 仅供无鉴权的本地测试；启用 JWT 后必须与 Token subject 一致，不能作为身份来源。
    user_id: str | None = None
    thread_id: str | None = None


class ResumeRequest(BaseModel):
    """恢复 interrupt() 暂停流程时由用户补充的内容。"""

    value: dict[str, Any] | str


class PauseAckResponse(BaseModel):
    """用户 Pause 确认（ADR-014）；未收到 resumable=true 前前端不得宣称可继续。"""

    run_id: str = Field(alias="runId")
    session_id: str | None = Field(default=None, alias="sessionId")
    status: Literal["PAUSED_BY_USER", "PAUSE_REQUESTED"] = "PAUSED_BY_USER"
    checkpoint_id: str | None = Field(default=None, alias="checkpointId")
    resumable: bool = True

    model_config = {"populate_by_name": True}


class CancelAckResponse(BaseModel):
    """用户放弃当前 pending run（不再 resume）。"""

    run_id: str = Field(alias="runId")
    session_id: str | None = Field(default=None, alias="sessionId")
    status: Literal["ABANDONED"] = "ABANDONED"
    resumable: bool = False

    model_config = {"populate_by_name": True}


class ChatRequest(BaseModel):
    """统一聊天页面请求；用户身份只来自 JWT / 游客归一。"""

    session_id: str | None = Field(default=None, alias="sessionId", max_length=128)
    message: str = Field(min_length=1, max_length=20_000)
    regenerate: bool = False
    # 会话级 Skill 开关快照：None=未提供，[]=本对话全部关闭。
    enabled_skill_ids: list[str] | None = Field(default=None, alias="enabledSkillIds", max_length=32)

    @field_validator("enabled_skill_ids")
    @classmethod
    def _validate_enabled_skill_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(set(value)) != len(value):
            raise ValueError("enabledSkillIds 不得重复")
        for item in value:
            text = str(item).strip()
            if not text or not _SKILL_ID_PATTERN.fullmatch(text):
                raise ValueError(f"非法 enabledSkillIds 项: {item!r}")
        return [str(item).strip() for item in value]


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


#: 设计文档 §7.8.1 结果块类型；未知类型由前端降级，投影层只发出本枚举。
ResultBlockType = Literal["ScoreCard", "AnalysisReport", "SuitabilityDraft", "PortfolioHealth", "QuoteTable"]

#: C-2 固定披露（设计文档 §7.8.4）；投影层写入，不接受模型改写。
SUITABILITY_DISCLOSURE = "本结果仅为风险匹配筛查草稿，不构成投资建议。"


class ResultBlock(BaseModel):
    """工具 Observation 直接投影的结果块；payload 数字不得经 LLM 转述。"""

    type: ResultBlockType
    payload: dict[str, Any]
    observation_id: str | None = None
    source: str | None = None
    data_time: str | None = None


class ChatResultV2(BaseModel):
    """SSE ``response.final`` 载荷（设计文档 §6.2 / §7.8.1）。"""

    answer: str = ""
    blocks: list[ResultBlock] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    audit_codes: list[str] = Field(default_factory=list)
    disclosures: list[str] = Field(default_factory=list)
