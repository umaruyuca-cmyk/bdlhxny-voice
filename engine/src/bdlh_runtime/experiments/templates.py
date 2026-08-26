"""实验模板注册表(混合路线阶段 B1)。

第一版以版本化代码常量为单一真源(不建数据库模板表)。每个正式模板:

- 只有一个主要自变量(点分路径表示),其余条件全部冻结;
- 变体值由模板定义,客户端不能直接上传任意变体数组;
- 超过角色或模板上限时拒绝;变体覆盖冻结字段时执行前失败;
- 多变量交叉只能使用显式标记的专项/诊断模板,不能伪装成单变量。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from bdlh_runtime.experiments.run_config import (
    EXECUTION_ENGINE_NATIVE_TOOL_CALLING,
    GOVERNANCE_OFF,
    GOVERNANCE_STANDARD,
    TOOL_DELIVERY_ALL,
    TOOL_DELIVERY_SEARCH,
    FixedConditionViolation,
    LimitsConfig,
    ModelParams,
    RunConfig,
    RunConfigError,
    ToolsConfig,
    assert_single_variable,
    assert_temperature_top_p_isolation,
    confirm_model_params,
    hash_of,
)

EXPERIMENT_DEFINITION_VERSION = "run-config-v2"

#: 模板分类
CLASSIFICATION_FORMAL = "formal-single-variable"
CLASSIFICATION_CROSS = "special-cross"

ROLE_ANONYMOUS = "anonymous"
ROLE_OWNER = "owner"


class TemplatePlanError(ValueError):
    """模板批次计划不合法:权限、重复次数、上限、变体覆盖或能力不支持。"""


@dataclass(frozen=True)
class VariantSpec:
    """一个模板变体:标签 + 相对基础配置的覆盖(只允许触碰主自变量路径)。"""

    label: str
    overrides: tuple[tuple[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "overrides": dict(self.overrides)}


@dataclass(frozen=True)
class ExperimentTemplate:
    """一个实验模板的完整定义(版本化常量)。"""

    template_id: str
    version: int
    purpose: str
    #: 唯一主要自变量(点分路径;温度模板含 requested/effective 两个键)
    independent_variable: tuple[str, ...]
    independent_variable_label: str
    variants: tuple[VariantSpec, ...]
    #: 基础运行配置(变体在其上覆盖;全部字段即冻结条件)
    base_config: RunConfig
    allowed_test_types: tuple[str, ...]
    anonymous_allowed: bool
    owner_allowed: bool
    repeat_count_range: tuple[int, int]
    max_runs_per_batch: int
    result_metrics: tuple[str, ...]
    classification: str
    #: 允许所有者覆盖的高级设置路径白名单(匿名不可用)
    advanced_allowed_paths: tuple[str, ...] = ()
    #: 允许「只生成输入、不自动运行」(上下文模板)
    allow_context_only: bool = False
    #: 需要模型能力支持(温度模板)
    requires_capability: str | None = None
    notes: str = ""

    def to_payload(self) -> dict[str, Any]:
        """公开形态:目的、自变量、变体、冻结条件与权限(不含评判细节)。"""
        return {
            "template_id": self.template_id,
            "version": self.version,
            "purpose": self.purpose,
            "classification": self.classification,
            "independent_variable": list(self.independent_variable),
            "independent_variable_label": self.independent_variable_label,
            "variants": [variant.as_dict() for variant in self.variants],
            "frozen_conditions": self.base_config.to_payload(),
            "allowed_test_types": list(self.allowed_test_types),
            "anonymous_allowed": self.anonymous_allowed,
            "owner_allowed": self.owner_allowed,
            "repeat_count_range": list(self.repeat_count_range),
            "max_runs_per_batch": self.max_runs_per_batch,
            "result_metrics": list(self.result_metrics),
            "advanced_allowed_paths": list(self.advanced_allowed_paths),
            "allow_context_only": self.allow_context_only,
            "requires_capability": self.requires_capability,
            "notes": self.notes,
        }


#: ── 工具可用性降级预设(版本化 + 哈希;匿名只能选预设) ─────────────────────

TOOL_EXCLUSION_PRESET_VERSION = "tool-exclusion-presets-v1"


@dataclass(frozen=True)
class ToolExclusionPreset:
    """版本化工具排除预设:完整目录 / 移除首选 / 同时移除首选与替代。"""

    preset_id: str
    description: str
    excluded_tools: tuple[str, ...]


_TOOL_EXCLUSION_PRESETS: tuple[ToolExclusionPreset, ...] = (
    ToolExclusionPreset("full-catalog", "完整目录(不移除任何工具)", ()),
    ToolExclusionPreset(
        "remove-preferred",
        "移除首选工具但保留替代工具",
        ("weather.get_forecast",),
    ),
    ToolExclusionPreset(
        "remove-preferred-and-alternative",
        "同时移除首选与替代工具",
        ("weather.get_forecast", "web.search"),
    ),
)


def tool_exclusion_presets() -> tuple[ToolExclusionPreset, ...]:
    return _TOOL_EXCLUSION_PRESETS


def get_tool_exclusion_preset(preset_id: str) -> ToolExclusionPreset:
    for preset in _TOOL_EXCLUSION_PRESETS:
        if preset.preset_id == preset_id:
            return preset
    raise TemplatePlanError(f"未知工具排除预设:{preset_id!r};可用:{[p.preset_id for p in _TOOL_EXCLUSION_PRESETS]}")


def tool_exclusion_preset_hash(preset: ToolExclusionPreset) -> str:
    return hash_of(
        {
            "preset_version": TOOL_EXCLUSION_PRESET_VERSION,
            "preset_id": preset.preset_id,
            "excluded_tools": sorted(preset.excluded_tools),
        }
    )


def known_tool_names() -> frozenset[str]:
    """排除项允许列表 = 对比用例目录快照(请求不能加入不存在的工具)。"""
    from bdlh_runtime.experiments.tool_catalog_snapshot import snapshot_tool_names

    return snapshot_tool_names()


#: ── 内置模板(第一版) ──────────────────────────────────────────────────────

_NATIVE_BASE = RunConfig(
    execution_engine=EXECUTION_ENGINE_NATIVE_TOOL_CALLING,
    tool_delivery=TOOL_DELIVERY_ALL,
    governance_profile=GOVERNANCE_STANDARD,
    context_strategy="full",
    model=ModelParams(),
    limits=LimitsConfig(max_agent_steps=4, max_tool_calls=6, max_calls_per_tool=2),
    tools=ToolsConfig(),
)

TEMPLATES: dict[str, ExperimentTemplate] = {}


def _register(template: ExperimentTemplate) -> None:
    _validate_template(template)
    TEMPLATES[template.template_id] = template


def _validate_template(template: ExperimentTemplate) -> None:
    """注册期守卫:正式模板唯一自变量、变体只触碰自变量路径、分类合法。"""
    if template.classification not in {CLASSIFICATION_FORMAL, CLASSIFICATION_CROSS}:
        raise RunConfigError(f"模板 {template.template_id} 分类非法:{template.classification}")
    if template.classification != CLASSIFICATION_FORMAL:
        return  # 交叉/诊断模板不要求单一自变量
    for variant in template.variants:
        for path, _value in variant.overrides:
            if path not in template.independent_variable:
                raise RunConfigError(
                    f"模板 {template.template_id} 变体 {variant.label} 覆盖了自变量之外的路径 {path}"
                )
    for variant in template.variants:
        config = template.base_config.with_overrides(dict(variant.overrides))
        config.validate_for_formal_template()
    assert_temperature_top_p_isolation(template.independent_variable)
    configs = [template.base_config.with_overrides(dict(v.overrides)) for v in template.variants]
    try:
        assert_single_variable(configs, variable_paths=template.independent_variable, label=template.template_id)
    except FixedConditionViolation as exc:
        raise RunConfigError(f"模板 {template.template_id} 变体破坏冻结条件:{exc}") from exc


_register(
    ExperimentTemplate(
        template_id="context-strategy-comparison",
        version=1,
        purpose="同一原生 Tool Calling 底座上比较四种上下文组织方式(4×1)",
        independent_variable=("context_strategy",),
        independent_variable_label="context_strategy",
        variants=(
            VariantSpec("full", (("context_strategy", "full"),)),
            VariantSpec("recent-window", (("context_strategy", "recent-window"),)),
            VariantSpec("single-summary", (("context_strategy", "single-summary"),)),
            VariantSpec("budgeted", (("context_strategy", "budgeted"),)),
        ),
        base_config=_NATIVE_BASE,
        allowed_test_types=("COMPRESSION_CASE",),
        anonymous_allowed=True,
        owner_allowed=True,
        repeat_count_range=(1, 1),
        max_runs_per_batch=4,
        result_metrics=("original_tokens", "working_tokens", "build_duration_ms", "compression_extra_tokens",
                        "required_retained", "key_facts_retained", "omitted_items", "compiled_context_hash"),
        allow_context_only=True,
        classification=CLASSIFICATION_FORMAL,
        notes="可以只生成四份上下文,不自动创建 Agent 运行;变体必须复用同一 Session 版本、当前事件、工具目录和 Mock",
    )
)
_register(
    ExperimentTemplate(
        template_id="governance-on-off",
        version=1,
        purpose="同一循环、同一模型、同一 Prompt、同一完整工具目录与 Mock,只改变治理档位",
        independent_variable=("governance_profile",),
        independent_variable_label="governance_profile",
        variants=(
            VariantSpec("off", (("governance_profile", GOVERNANCE_OFF),)),
            VariantSpec("standard", (("governance_profile", GOVERNANCE_STANDARD),)),
        ),
        base_config=_NATIVE_BASE,
        allowed_test_types=("COMPARISON_CASE",),
        anonymous_allowed=True,
        owner_allowed=True,
        repeat_count_range=(1, 5),
        max_runs_per_batch=10,
        result_metrics=("interception_recall", "false_interception_rate", "unauthorized_mock_executions",
                        "unconfirmed_write_mock_executions", "recovery_after_rejection", "bypassed_event_count",
                        "audit_completeness"),
        classification=CLASSIFICATION_FORMAL,
        notes="两组使用同一个 AgentLoop 实现;off 档旁路事件可见但只执行 Mock",
    )
)
_register(
    ExperimentTemplate(
        template_id="tool-delivery-comparison",
        version=1,
        purpose="同一完整目录、相同排除项、相同 Mock 与治理配置下比较 all / search 两种工具提供方式",
        independent_variable=("tool_delivery", "tools.search_top_k"),
        independent_variable_label="tool_delivery",
        variants=(
            VariantSpec("all", (("tool_delivery", TOOL_DELIVERY_ALL),)),
            VariantSpec("search", (("tool_delivery", TOOL_DELIVERY_SEARCH), ("tools.search_top_k", 3))),
        ),
        base_config=_NATIVE_BASE,
        allowed_test_types=("COMPARISON_CASE",),
        anonymous_allowed=True,
        owner_allowed=True,
        repeat_count_range=(1, 5),
        max_runs_per_batch=10,
        result_metrics=("retrieval_error", "selection_error", "invocation_error", "final_answer_error",
                        "tool_not_visible_events", "search_rounds", "tool_schema_tokens"),
        classification=CLASSIFICATION_FORMAL,
        notes="search 的候选范围 = 完整目录 − 同一排除项(eligible catalog);回退策略固定为 none 并记录",
    )
)
_register(
    ExperimentTemplate(
        template_id="temperature-stability",
        version=1,
        purpose="同一定义下比较温度档位的输出稳定性(每档多次重复)",
        independent_variable=("model.temperature_requested", "model.temperature_effective"),
        independent_variable_label="temperature_effective",
        variants=(
            VariantSpec("t0.0", (("model.temperature_requested", 0.0),)),
            VariantSpec("t0.1", (("model.temperature_requested", 0.1),)),
            VariantSpec("t0.3", (("model.temperature_requested", 0.3),)),
            VariantSpec("t0.7", (("model.temperature_requested", 0.7),)),
        ),
        base_config=_NATIVE_BASE,
        allowed_test_types=("COMPARISON_CASE",),
        anonymous_allowed=False,
        owner_allowed=True,
        repeat_count_range=(3, 5),
        max_runs_per_batch=20,
        result_metrics=("success_rate", "answer_stability", "duration_ms_spread", "token_spread"),
        requires_capability="supports_temperature",
        classification=CLASSIFICATION_FORMAL,
        notes="不支持温度的模型不能创建该模板批次;温度与 top_p 不同时变化;effective 由适配器确认",
    )
)
_register(
    ExperimentTemplate(
        template_id="tool-availability-degradation",
        version=1,
        purpose="版本化工具排除预设下的能力降级行为:首选路径 / 替代路径 / 诚实说明限制",
        independent_variable=("tools.excluded_tools",),
        independent_variable_label="excluded_tools(版本化预设)",
        variants=tuple(
            VariantSpec(preset.preset_id, (("tools.excluded_tools", list(preset.excluded_tools)),))
            for preset in _TOOL_EXCLUSION_PRESETS
        ),
        base_config=_NATIVE_BASE,
        allowed_test_types=("COMPARISON_CASE",),
        anonymous_allowed=True,
        owner_allowed=True,
        repeat_count_range=(1, 5),
        max_runs_per_batch=15,
        result_metrics=("acceptable_path_hit", "honest_limitation_rate", "fabrication_rate",
                        "excluded_tool_called", "success_claimed_without_call"),
        classification=CLASSIFICATION_FORMAL,
        notes="匿名用户只能选择模板预设;所有者可在允许列表内创建新预设;排除项不能加入不存在的工具",
    )
)
_register(
    ExperimentTemplate(
        template_id="max-agent-steps-stability",
        version=1,
        purpose="固定 max_tool_calls、模型与其他条件,只改变单次运行最大步数(3/4/5)",
        independent_variable=("limits.max_agent_steps",),
        independent_variable_label="max_agent_steps",
        variants=(
            VariantSpec("steps-3", (("limits.max_agent_steps", 3),)),
            VariantSpec("steps-4", (("limits.max_agent_steps", 4),)),
            VariantSpec("steps-5", (("limits.max_agent_steps", 5),)),
        ),
        base_config=_NATIVE_BASE,
        allowed_test_types=("COMPARISON_CASE",),
        anonymous_allowed=False,
        owner_allowed=True,
        repeat_count_range=(1, 5),
        max_runs_per_batch=15,
        result_metrics=("completion_rate", "truncation_rate", "token_usage", "duration_ms"),
        classification=CLASSIFICATION_FORMAL,
        advanced_allowed_paths=("limits.max_tool_calls", "limits.max_calls_per_tool"),
        notes="max_agent_steps 与批次 repeat_count 始终分开;观察完成、截断、Token 和时长",
    )
)
def get_template(template_id: str) -> ExperimentTemplate:
    try:
        return TEMPLATES[template_id]
    except KeyError:
        raise TemplatePlanError(
            f"未知实验模板:{template_id!r};可用:{sorted(TEMPLATES)}"
        ) from None


def list_templates(*, role: str | None = None) -> list[ExperimentTemplate]:
    rows = list(TEMPLATES.values())
    if role == ROLE_ANONYMOUS:
        rows = [row for row in rows if row.anonymous_allowed]
    return rows


def template_registry_payload(*, role: str | None = None) -> dict[str, Any]:
    """页面/接口用模板清单:目的、自变量、变体、冻结条件与精确运行数。"""
    templates = []
    for template in list_templates(role=role):
        payload = template.to_payload()
        formula = f"{len(template.variants)}个变体×repeat_count" if template.variants else "无变体"
        templates.append({**payload, "run_count_formula": formula})
    return {
        "experiment_definition_version": EXPERIMENT_DEFINITION_VERSION,
        "templates": templates,
    }


# ── 批次计划 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlannedRun:
    """计划内一次运行:变体标签 × 重复编号 → 精确运行配置。"""

    run_id: str
    variant_label: str
    repeat_index: int
    run_config: RunConfig

    @property
    def config_hash(self) -> str:
        return self.run_config.config_hash


@dataclass(frozen=True)
class TemplateBatchPlan:
    """模板 → 运行配置变体 → 精确运行数(执行前全部校验完成)。"""

    template_id: str
    template_version: int
    classification: str
    independent_variable: tuple[str, ...]
    runs: tuple[PlannedRun, ...]
    fixed_conditions: dict[str, Any]
    fixed_conditions_hash: str
    run_count: int
    context_only: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "template_version": self.template_version,
            "classification": self.classification,
            "independent_variable": list(self.independent_variable),
            "run_count": self.run_count,
            "context_only": self.context_only,
            "fixed_conditions": self.fixed_conditions,
            "fixed_conditions_hash": self.fixed_conditions_hash,
            "runs": [
                {
                    "run_id": run.run_id,
                    "variant_label": run.variant_label,
                    "repeat_index": run.repeat_index,
                    "config_hash": run.config_hash,
                    "run_config": run.run_config.config_payload_with_hash(),
                }
                for run in self.runs
            ],
        }


def plan_template_batch(
    template_id: str,
    *,
    repeat_count: int,
    role: str = ROLE_OWNER,
    advanced: dict[str, Any] | None = None,
    preset_id: str | None = None,
    owner_excluded_tools: tuple[str, ...] | list[str] | None = None,
    model_capability: Any = None,
    context_only: bool = False,
    variant_labels: tuple[str, ...] | list[str] | None = None,
) -> TemplateBatchPlan:
    """模板 → 运行配置变体 → 精确运行数;全部拒绝路径在执行前完成。

    - 角色权限:匿名只能使用允许匿名的模板与预设,不能提交高级设置;
    - 重复次数必须落在模板区间;总运行数不得超过模板/角色上限;
    - ``advanced`` 只接受模板白名单内的路径(仅所有者);
    - ``variant_labels`` 只能在模板既有变体中做子集选择(不能上传任意变体);
    - 温度模板要求模型能力确认支持温度,否则拒绝创建批次;
    - 工具排除:匿名只能选预设;所有者自定义排除项必须 ⊆ 允许列表。
    """
    template = get_template(template_id)
    if role == ROLE_ANONYMOUS and not template.anonymous_allowed:
        raise TemplatePlanError(f"模板 {template_id} 不对匿名用户开放")
    if role == ROLE_OWNER and not template.owner_allowed:
        raise TemplatePlanError(f"模板 {template_id} 不对所有者开放")
    lo, hi = template.repeat_count_range
    if not isinstance(repeat_count, int) or not (lo <= repeat_count <= hi):
        raise TemplatePlanError(f"模板 {template_id} repeat_count 只能取 {lo}..{hi},收到 {repeat_count!r}")

    if context_only and not template.allow_context_only:
        raise TemplatePlanError(f"模板 {template_id} 不支持 context-only(不会自动运行 Agent)")

    base = template.base_config
    overrides_advanced: dict[str, Any] = {}
    if advanced:
        if role != ROLE_OWNER:
            raise TemplatePlanError("匿名测试不能提交高级设置;只能使用模板预设")
        unknown = set(advanced) - set(template.advanced_allowed_paths)
        if unknown:
            raise TemplatePlanError(
                f"高级设置字段越出模板白名单:{sorted(unknown)};允许:{list(template.advanced_allowed_paths)}"
            )
        overrides_advanced.update(advanced)

    # 变体选择:只能是模板既有变体的子集(不能上传任意变体数组)
    selected_variants = template.variants
    if variant_labels is not None:
        wanted = list(variant_labels)
        known = {variant.label for variant in template.variants}
        unknown = [label for label in wanted if label not in known]
        if unknown:
            raise TemplatePlanError(f"变体标签不在模板定义中:{unknown};可用:{sorted(known)}")
        if not wanted:
            raise TemplatePlanError("变体子集不能为空")
        selected_variants = tuple(v for v in template.variants if v.label in set(wanted))

    # 工具排除预设(匿名) / 所有者自定义排除项
    preset_hash = ""
    if template.template_id == "tool-availability-degradation":
        if preset_id is not None:
            preset = get_tool_exclusion_preset(preset_id)
            preset_hash = tool_exclusion_preset_hash(preset)
            selected_variants = tuple(
                VariantSpec(preset.preset_id, (("tools.excluded_tools", list(preset.excluded_tools)),))
                for preset in (preset,)
            )
        elif owner_excluded_tools is not None and role != ROLE_OWNER:
            raise TemplatePlanError("匿名用户只能选择模板预设,不能自定义排除项")
        elif owner_excluded_tools is not None:
            excluded = tuple(sorted(set(str(name) for name in owner_excluded_tools)))
            unknown = [name for name in excluded if name not in known_tool_names()]
            if unknown:
                raise TemplatePlanError(f"排除项包含不存在或不在允许列表内的工具:{unknown}")
            selected_variants = (
                VariantSpec("owner-custom", (("tools.excluded_tools", list(excluded)),)),
            )
            preset_hash = hash_of(
                {"preset_version": TOOL_EXCLUSION_PRESET_VERSION, "preset_id": "owner-custom",
                 "excluded_tools": list(excluded)}
            )

    # 温度模板:能力确认(不支持温度的模型不能创建批次)
    capability = model_capability
    if template.requires_capability != "supports_temperature":
        capability = None  # 非温度模板不消费能力描述
    elif capability is None or not getattr(capability, "supports_temperature", False):
        raise TemplatePlanError(
            "temperature-stability 模板需要模型适配器确认支持温度参数;当前模型不支持或未提供能力描述,不能创建批次"
        )

    planned: list[PlannedRun] = []
    variant_configs: list[RunConfig] = []
    for variant in selected_variants:
        overrides = {**overrides_advanced, **dict(variant.overrides)}
        config = base.with_overrides(overrides)
        if template.classification == CLASSIFICATION_FORMAL:
            config.validate_for_formal_template()
        else:
            config.validate()
        if template.requires_capability == "supports_temperature" and capability is not None:
            config = replace(config, model=confirm_model_params(config.model, capability))
            config.validate()
        variant_configs.append(config)
        for repeat_index in range(repeat_count):
            planned.append(
                PlannedRun(
                    run_id=f"{template_id}:{variant.label}:r{repeat_index}",
                    variant_label=variant.label,
                    repeat_index=repeat_index,
                    run_config=config,
                )
            )

    # 单变量纪律:正式模板所有变体只允许在自变量路径上不同(执行前失败)
    if template.classification == CLASSIFICATION_FORMAL and len(variant_configs) > 1:
        assert_single_variable(
            variant_configs, variable_paths=template.independent_variable, label=f"模板 {template_id}"
        )

    run_count = 0 if context_only else len(planned)
    role_cap = 8 if role == ROLE_ANONYMOUS else template.max_runs_per_batch
    if run_count > role_cap:
        raise TemplatePlanError(
            f"计划运行数 {run_count} 超过上限(角色 {role} 上限 {role_cap},模板上限 {template.max_runs_per_batch});"
            "不生成所有参数的笛卡尔积"
        )

    fixed_conditions: dict[str, Any] = {
        "experiment_definition_version": EXPERIMENT_DEFINITION_VERSION,
        "template_id": template.template_id,
        "template_version": template.version,
        "template_classification": template.classification,
        "independent_variable": list(template.independent_variable),
        "repeat_count": repeat_count,
        "role": role,
        "variant_labels": [variant.label for variant in selected_variants],
        "frozen_run_config": base.with_overrides(overrides_advanced).to_payload(),
    }
    if preset_hash:
        fixed_conditions["tool_exclusion_preset_hash"] = preset_hash
    if template.classification != CLASSIFICATION_FORMAL:
        fixed_conditions["experiment_definition_note"] = "多变量交叉专项,不能做单变量归因"
    return TemplateBatchPlan(
        template_id=template.template_id,
        template_version=template.version,
        classification=template.classification,
        independent_variable=template.independent_variable,
        runs=() if context_only else tuple(planned),
        fixed_conditions=fixed_conditions,
        fixed_conditions_hash=hash_of(fixed_conditions),
        run_count=run_count,
        context_only=context_only,
    )


__all__ = [
    "CLASSIFICATION_CROSS",
    "CLASSIFICATION_FORMAL",
    "EXPERIMENT_DEFINITION_VERSION",
    "ExperimentTemplate",
    "PlannedRun",
    "ROLE_ANONYMOUS",
    "ROLE_OWNER",
    "TEMPLATES",
    "TemplateBatchPlan",
    "TemplatePlanError",
    "VariantSpec",
    "get_template",
    "get_tool_exclusion_preset",
    "known_tool_names",
    "list_templates",
    "plan_template_batch",
    "template_registry_payload",
    "tool_exclusion_preset_hash",
    "tool_exclusion_presets",
    "TOOL_EXCLUSION_PRESET_VERSION",
]
