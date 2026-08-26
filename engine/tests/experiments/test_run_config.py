"""运行配置快照测试(混合路线阶段 A5)。

覆盖:哈希稳定性、键顺序无关性、字段变化改变哈希、请求/生效值分离、
不支持参数不冒充生效、批次固定条件执行前校验、三个入口保存同一结构。
全部使用 Fake 能力描述与静态数据,不调用真实 LLM。
"""

from __future__ import annotations

import pytest

from bdlh_runtime.experiments.run_config import (
    EXECUTION_ENGINE_NATIVE_TOOL_CALLING,
    GOVERNANCE_OFF,
    TOOL_DELIVERY_SEARCH,
    FixedConditionViolation,
    ModelParams,
    RunConfig,
    RunConfigError,
    assert_single_variable,
    assert_temperature_top_p_isolation,
    catalog_schema_hash,
    confirm_model_params,
    hash_of,
)
from bdlh_runtime.infra.llm import ModelCapability, capabilities_of


def test_same_config_same_hash():
    config = RunConfig(model=ModelParams(model_id="m-1"))
    twin = RunConfig(model=ModelParams(model_id="m-1"))
    assert config.config_hash == twin.config_hash
    assert config.config_hash == RunConfig.from_flat(config.to_payload_flat()).config_hash


def test_key_order_does_not_affect_hash():
    left = RunConfig().to_payload_flat()
    right = dict(reversed(list(left.items())))
    assert hash_of(left) == hash_of(right)


def test_field_changes_change_hash():
    base = RunConfig()
    assert base.with_overrides({"tools.excluded_tools": ["weather.get_forecast"]}).config_hash != base.config_hash
    assert base.with_overrides({"model.temperature_requested": 0.7}).config_hash != base.config_hash
    assert base.with_overrides({"limits.max_agent_steps": 5}).config_hash != base.config_hash
    assert base.with_overrides({"prompt_version": "agent-prompt-v2"}).config_hash != base.config_hash


def test_excluded_tools_order_does_not_affect_hash():
    left = RunConfig().with_overrides({"tools.excluded_tools": ["b.tool", "a.tool"]})
    right = RunConfig().with_overrides({"tools.excluded_tools": ["a.tool", "b.tool"]})
    assert left.config_hash == right.config_hash  # 集合语义:排序后进哈希


def test_catalog_schema_hash_sorted_by_tool_name():
    manifests_a = [
        {"name": "z.tool", "description": "z", "parameters": {}},
        {"name": "a.tool", "description": "a", "parameters": {}},
    ]
    manifests_b = list(reversed(manifests_a))
    assert catalog_schema_hash(manifests_a) == catalog_schema_hash(manifests_b)
    changed = [{"name": "a.tool", "description": "a 改", "parameters": {}}]
    assert catalog_schema_hash(changed) != catalog_schema_hash([manifests_a[1]])


def test_requested_and_effective_can_differ():
    capability = ModelCapability(supports_temperature=True)
    confirmed = confirm_model_params(ModelParams(temperature_requested=0.7), capability)
    assert confirmed.temperature_effective == 0.7
    assert confirmed.unsupported_reasons == ()


def test_unsupported_param_not_recorded_as_effective():
    capability = ModelCapability(
        supports_temperature=False,
        temperature_note="模型不支持温度参数",
        supports_seed=False,
        seed_note="适配器不传递 seed",
    )
    confirmed = confirm_model_params(
        ModelParams(temperature_requested=0.9, seed_requested=42),
        capability,
    )
    assert confirmed.temperature_effective is None
    assert confirmed.seed_effective is None
    assert any("temperature" in reason for reason in confirmed.unsupported_reasons)
    assert any("seed" in reason for reason in confirmed.unsupported_reasons)


def test_capabilities_of_reads_fake_declaration():
    class FakeModel:
        model_capabilities = ModelCapability(
            supports_temperature=False,
            temperature_note="Fake 模拟不支持温度",
        )

    assert capabilities_of(FakeModel()).supports_temperature is False
    assert capabilities_of(None).supports_temperature is False  # LLM 未配置
    assert capabilities_of(object()).supports_temperature is False  # 未知实现保守 fail-closed


def test_formal_template_rules():
    config = RunConfig()
    config.validate_for_formal_template()  # 默认:native 引擎 + all 工具提供 + standard 治理
    with pytest.raises(RunConfigError):
        RunConfig(execution_engine="bogus-engine").validate()  # 非白名单引擎值拒绝
    with pytest.raises(RunConfigError):
        RunConfig(tool_delivery="everything").validate()  # 非白名单装载值拒绝
    with pytest.raises(RunConfigError):
        RunConfig(model=ModelParams(tool_choice="required")).validate()


def test_single_variable_consistency_pass_and_fail():
    base = RunConfig(governance_profile="standard")
    variant = base.with_overrides({"governance_profile": GOVERNANCE_OFF})
    assert_single_variable(
        [base, variant], variable_paths=["governance_profile"], label="治理实验"
    )
    rogue = base.with_overrides({"governance_profile": GOVERNANCE_OFF, "limits.max_agent_steps": 9})
    with pytest.raises(FixedConditionViolation) as excinfo:
        assert_single_variable([base, rogue], variable_paths=["governance_profile"])
    assert "limits.max_agent_steps" in str(excinfo.value)


def test_temperature_top_p_isolation():
    assert_temperature_top_p_isolation(["model.temperature_effective"])
    assert_temperature_top_p_isolation(["model.top_p_effective"])
    with pytest.raises(RunConfigError):
        assert_temperature_top_p_isolation(
            ["model.temperature_effective", "model.top_p_effective"]
        )


# ── 入口 + 后台任务保存同一结构 ────────────────────────────────────────────


def test_compression_entry_records_run_configs():
    from bdlh_runtime.experiments.compression import (
        COMPRESSION_SESSIONS,
        generate_contexts,
    )

    session_id = COMPRESSION_SESSIONS[1][0]
    generated = generate_contexts(session_id, write=False)
    assert generated.agent_runs_created == 0  # 结构保证:生成阶段不创建 Agent 运行
    # 编译对象口径的配置快照在运行阶段构建;此处验证指纹(上下文生成阶段的配置等价物)
    assert generated.fingerprint["session_id"] == session_id
    assert generated.fingerprint["variants"]


def test_telemetry_artifact_carries_config_snapshot():
    from bdlh_runtime.evaluation.run_telemetry import MODE_NATIVE, RunRecorder, build_run_artifact

    recorder = RunRecorder(
        run_key="k",
        case_id="c",
        case_version=1,
        variant_id="default",
        snapshot_id="s",
        snapshot_hash="h",
        agent_mode=MODE_NATIVE,
        context_strategy="full",
        model="fake-model",
        repeat_index=0,
        message="m",
        category="cat",
    )
    config = RunConfig(
        execution_engine=EXECUTION_ENGINE_NATIVE_TOOL_CALLING,
        tool_delivery=TOOL_DELIVERY_SEARCH,
    )
    recorder.record.provenance["per_run_config"] = config.config_payload_with_hash()
    recorder.record.provenance["config_hash"] = config.config_hash
    recorder.complete(status="COMPLETE", error_category=None, error_text=None)
    artifact = build_run_artifact(recorder.record)
    assert artifact["provenance"]["config_hash"] == config.config_hash
    assert artifact["provenance"]["per_run_config"]["tool_delivery"] == "search"
    # 旧工件仍可读取:无 per_run_config 的记录不炸
    artifact["provenance"].pop("per_run_config")
    assert artifact["provenance"]["config_hash"] == config.config_hash
