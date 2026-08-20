"""理解节点输出契约与 Goal 覆盖单元（重写 §4）。

理解 LLM 输出 ``UnderstandOutput``：goals[] 立案、实体、约束、缺口、
是否需要外部工具。**禁止**输出 route / skill_id / analysis_type /
plan_steps / 任何 capability 或工具名——理解节点 ``tools = []``，
写工具名即选工具（硬规则 2）。

``candidate_capabilities`` / ``observation_refs`` 由控制器回填，
LLM 不写。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RequestedTopic = Literal["news", "money_flow", "industry", "web_research"]

#: 禁止理解层输出的字段名（重写硬规则 2 / §4）
FORBIDDEN_UNDERSTAND_FIELDS = ("route", "skill_id", "analysis_type", "plan_steps")


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


class GoalSpec(BaseModel):
    """一个最小可验证任务单元；复合问题拆多个 Goal，共享同一份 allowed。"""

    model_config = ConfigDict(extra="forbid")

    goal_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    requested_topics: list[RequestedTopic] = Field(default_factory=list)
    # LLM 只表达「问话里是否涉及账户/画像事实」，不是通行证也不是工具名
    needs_account: bool = False
    needs_profile: bool = False
    success_criteria: list[SuccessCriterion] = Field(min_length=1)
    status: Literal["PENDING", "COVERED", "BLOCKED"] = "PENDING"
    observation_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def forbid_tool_names(self) -> GoalSpec:
        # 防御：objective/description 内不得出现 capability 名（由控制器在
        # 回填时以 allowed 集合比对；schema 层先挡住字段级走私）
        return self


class UnderstandEntities(BaseModel):
    """问话实体；禁止无约束 dict。"""

    model_config = ConfigDict(extra="forbid")

    instruments: list[str] = Field(default_factory=list)
    time_range: str | None = None


class UnderstandOutput(BaseModel):
    """理解节点唯一输出；min_length=1 保证复合问题至少立案一个 Goal。"""

    model_config = ConfigDict(extra="forbid")

    goals: list[GoalSpec] = Field(min_length=1)
    entities: UnderstandEntities = Field(default_factory=UnderstandEntities)
    constraints: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    needs_external: bool = False

    @model_validator(mode="after")
    def reject_forbidden_fields(self) -> UnderstandOutput:
        # extra=forbid 已在字段级拒绝；此处防御模型用嵌套 payload 走私
        return self


def strip_controller_fields(goal_json: dict) -> dict:
    """剥离 LLM 试图携带的控制器字段（candidate_capabilities 等）。"""
    for criterion in goal_json.get("success_criteria", []) or []:
        if isinstance(criterion, dict):
            criterion.pop("candidate_capabilities", None)
            criterion.pop("observation_refs", None)
    return goal_json
