"""理解节点输出契约与 Goal 覆盖单元。

理解 LLM 输出 ``UnderstandOutput``：goals[] 立案、实体、约束、缺口、
是否需要外部数据，以及本轮的工具调用决策（``action``）。

``action`` 是 Function Calling 风格的工具调用指令：LLM 直接输出
``{"tool": "...", "parameters": {...}}``，由内核 dispatch 到对应域 handler。
``requested_topics`` 为自由字符串，合法主题由装配期注册表校验。
**禁止**输出 route / skill_id / plan_steps 等控制器字段。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RequestedTopic = str

#: 禁止理解层输出的字段名（选工具 / 类型路由走私）
FORBIDDEN_UNDERSTAND_FIELDS = ("route", "skill_id", "plan_steps")


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_UNDERSTAND_FIELDS:
                return True
            if _contains_forbidden_key(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


class SuccessCriterion(BaseModel):
    """一条可判定的成功标准。

    LLM 只填 criterion_id / topic / description；
    candidate_capabilities 与 observation_refs 由控制器回填。
    """

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    topic: RequestedTopic | None = None
    description: str = Field(min_length=1)
    # ── 控制器回填区：LLM 禁止输出 ──
    candidate_capabilities: list[str] = Field(default_factory=list)
    observation_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_forbidden_fields(cls, data: Any) -> Any:
        if _contains_forbidden_key(data):
            raise ValueError("Understand criterion contains forbidden field")
        return data


class GoalSpec(BaseModel):
    """一个最小可验证任务单元；复合问题拆多个 Goal，共享同一份 allowed。"""

    model_config = ConfigDict(extra="forbid")

    goal_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    requested_topics: list[RequestedTopic] = Field(default_factory=list)
    needs_account: bool = False
    needs_profile: bool = False
    success_criteria: list[SuccessCriterion] = Field(min_length=1)
    status: Literal["PENDING", "COVERED", "BLOCKED"] = "PENDING"
    observation_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_forbidden_fields(cls, data: Any) -> Any:
        if _contains_forbidden_key(data):
            raise ValueError("Understand goal contains forbidden field")
        return data


class UnderstandEntities(BaseModel):
    """问话实体；禁止无约束 dict。"""

    model_config = ConfigDict(extra="forbid")

    instruments: list[str] = Field(default_factory=list)
    time_range: str | None = None


class ActionSpec(BaseModel):
    """Function Calling 风格的工具调用指令。

    LLM 直接输出 ``{"tool": "...", "parameters": {...}}``，由内核 dispatch 到
    对应域 handler。``tool`` 必须是装配期注册的能力名；``parameters`` 是
    该工具的参数（结构由工具自身 schema 约束）。
    """

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class UnderstandOutput(BaseModel):
    """理解节点唯一输出；min_length=1 保证复合问题至少立案一个 Goal。"""

    model_config = ConfigDict(extra="forbid")

    goals: list[GoalSpec] = Field(min_length=1)
    entities: UnderstandEntities = Field(default_factory=UnderstandEntities)
    constraints: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    needs_external: bool = False
    action: ActionSpec | None = None
    # 控制器回填：走私拒绝等软失败原因码，LLM 不得写入。
    reason_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_forbidden_fields(cls, data: Any) -> Any:
        if _contains_forbidden_key(data):
            raise ValueError("Understand payload contains forbidden field")
        return data


def strip_controller_fields(goal_json: dict) -> dict:
    """剥离 LLM 试图携带的控制器字段（candidate_capabilities 等）。"""
    for criterion in goal_json.get("success_criteria", []) or []:
        if isinstance(criterion, dict):
            criterion.pop("candidate_capabilities", None)
            criterion.pop("observation_refs", None)
    return goal_json
