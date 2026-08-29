"""模板注册表、统一运行底座、治理开关与写确认测试(混合路线阶段 B6)。

全部使用 FakeChatModel / 冻结 Mock 执行器 / 内存确认仓储,不调用真实 LLM、
不执行 SQL、不运行正式实验。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.experiments.fixture_hash import fixture_content_hash
from bdlh_runtime.experiments.governance_metrics import (
    GOVERNANCE_PROBES,
    GovernanceProbeCase,
    evaluate_governance_probe,
    governance_metrics_for_run,
    summarize_governance_metrics,
)
from bdlh_runtime.experiments.run_config import (
    GOVERNANCE_OFF,
    GOVERNANCE_STANDARD,
    RunConfigError,
)
from bdlh_runtime.experiments.template_runner import run_native_agent, run_template_batch
from bdlh_runtime.experiments.templates import (
    CLASSIFICATION_FORMAL,
    ROLE_ANONYMOUS,
    ROLE_OWNER,
    TEMPLATES,
    ExperimentTemplate,
    TemplatePlanError,
    VariantSpec,
    get_template,
    get_tool_exclusion_preset,
    plan_template_batch,
    tool_exclusion_preset_hash,
)
from bdlh_runtime.guardrails.confirmations import (
    AUDIT_CONFIRMATION_ARGUMENTS_MISMATCH,
    AUDIT_CONFIRMATION_EXPIRED,
    AUDIT_CONFIRMATION_INVALID,
    AUDIT_CONFIRMATION_REQUIRED,
    AUDIT_CONFIRMATION_RUN_MISMATCH,
    AutoGrantConfirmationProvider,
    ConfirmationStore,
    DenyAllConfirmationProvider,
    hash_arguments,
)
from bdlh_runtime.guardrails.contracts import GuardrailContext
from bdlh_runtime.guardrails.middleware import GOVERNANCE_PROFILE_OFF, GovernanceMiddleware
from bdlh_runtime.infra.llm import ModelCapability
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog


class FakeChatModel:
    """按序返回预设 AIMessage;bind_tools 记录装载集合。"""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0
        self.bound_tools: list = []
        self.bind_history: list = []

    def bind_tools(self, tools, **_kwargs):
        snapshot = list(tools)
        self.bound_tools = snapshot
        self.bind_history.append(snapshot)
        return self

    async def ainvoke(self, messages, **_kwargs):
        if self._index >= len(self._responses):
            raise AssertionError("FakeChatModel 响应已耗尽")
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


# ── B1 模板注册表 ───────────────────────────────────────────────────────────


def test_every_formal_template_has_single_independent_variable():
    for template in TEMPLATES.values():
        if template.classification == CLASSIFICATION_FORMAL:
            assert template.independent_variable, template.template_id
            assert template.variants, template.template_id


def test_variant_overriding_frozen_field_is_rejected_at_registration():
    from bdlh_runtime.experiments import templates as templates_module

    rogue = ExperimentTemplate(
        template_id="rogue-template",
        version=1,
        purpose="变体触碰冻结字段的非法模板",
        independent_variable=("governance_profile",),
        independent_variable_label="governance_profile",
        variants=(VariantSpec("bad", (("governance_profile", "off"), ("limits.max_agent_steps", 9))),),
        base_config=TEMPLATES["governance-on-off"].base_config,
        allowed_test_types=("COMPARISON_CASE",),
        anonymous_allowed=False,
        owner_allowed=True,
        repeat_count_range=(1, 5),
        max_runs_per_batch=10,
        result_metrics=(),
        classification=CLASSIFICATION_FORMAL,
    )
    with pytest.raises(RunConfigError):
        templates_module._validate_template(rogue)
    assert "rogue-template" not in TEMPLATES


def test_repeat_range_and_caps_enforced():
    with pytest.raises(TemplatePlanError):
        plan_template_batch("governance-on-off", repeat_count=6)  # 区间 1..5
    # 匿名角色上限 8:2 变体 × 4 = 8 允许,× 5 = 10 拒绝
    assert plan_template_batch("governance-on-off", repeat_count=4, role=ROLE_ANONYMOUS).run_count == 8
    with pytest.raises(TemplatePlanError):
        plan_template_batch("governance-on-off", repeat_count=5, role=ROLE_ANONYMOUS)
    # 所有者上限 10:× 5 = 10 允许
    assert plan_template_batch("governance-on-off", repeat_count=5, role=ROLE_OWNER).run_count == 10


def test_client_cannot_upload_arbitrary_variants():
    with pytest.raises(TemplatePlanError):
        plan_template_batch("governance-on-off", repeat_count=1, variant_labels=["off", "nonexistent"])
    # 子集选择允许,但不能为空、不能传入未定义变体
    plan = plan_template_batch("governance-on-off", repeat_count=1, variant_labels=["off"])
    assert [run.variant_label for run in plan.runs] == ["off"]
    with pytest.raises(TemplatePlanError):
        plan_template_batch("governance-on-off", repeat_count=1, variant_labels=[])


def test_anonymous_cannot_submit_advanced_settings():
    with pytest.raises(TemplatePlanError):
        plan_template_batch(
            "max-agent-steps-stability", repeat_count=1, role=ROLE_ANONYMOUS
        )  # 模板本身不匿名开放
    with pytest.raises(TemplatePlanError):
        plan_template_batch(
            "governance-on-off",
            repeat_count=1,
            role=ROLE_ANONYMOUS,
            advanced={"model.seed_requested": 1},
        )


def test_owner_advanced_fields_whitelisted():
    template = TEMPLATES["max-agent-steps-stability"]
    assert template.advanced_allowed_paths  # 模板声明了白名单
    with pytest.raises(TemplatePlanError):
        plan_template_batch(
            "governance-on-off", repeat_count=1, advanced={"context.token_budget": 999}
        )  # governance 模板未开放该路径


def test_temperature_template_requires_capability():
    with pytest.raises(TemplatePlanError):
        plan_template_batch("temperature-stability", repeat_count=3)
    with pytest.raises(TemplatePlanError):
        plan_template_batch(
            "temperature-stability", repeat_count=3, model_capability=ModelCapability(supports_temperature=False)
        )
    plan = plan_template_batch(
        "temperature-stability",
        repeat_count=3,
        model_capability=ModelCapability(supports_temperature=True),
    )
    assert plan.run_count == 12  # 4 档 × 3 次
    effective = {run.run_config.model.temperature_effective for run in plan.runs}
    assert effective == {0.0, 0.1, 0.3, 0.7}


def test_tool_exclusion_presets_versioned_and_hashed():
    preset = get_tool_exclusion_preset("remove-preferred")
    assert preset.excluded_tools == ("weather.get_forecast",)
    assert tool_exclusion_preset_hash(preset) == tool_exclusion_preset_hash(preset)
    assert (
        tool_exclusion_preset_hash(preset)
        != tool_exclusion_preset_hash(get_tool_exclusion_preset("full-catalog"))
    )
    plan = plan_template_batch(
        "tool-availability-degradation", repeat_count=3, role=ROLE_ANONYMOUS, preset_id="remove-preferred"
    )
    assert plan.runs[0].run_config.tools.excluded_tools == ("weather.get_forecast",)
    assert plan.fixed_conditions["tool_exclusion_preset_hash"]
    with pytest.raises(TemplatePlanError):
        plan_template_batch("tool-availability-degradation", repeat_count=1, preset_id="no-such-preset")


def test_owner_custom_exclusion_cannot_include_unknown_tools():
    plan = plan_template_batch(
        "tool-availability-degradation",
        repeat_count=1,
        role=ROLE_OWNER,
        owner_excluded_tools=["weather.get_forecast"],
    )
    assert plan.runs[0].run_config.tools.excluded_tools == ("weather.get_forecast",)
    with pytest.raises(TemplatePlanError):
        plan_template_batch(
            "tool-availability-degradation",
            repeat_count=1,
            role=ROLE_OWNER,
            owner_excluded_tools=["not.a.tool"],
        )
    with pytest.raises(TemplatePlanError):
        plan_template_batch(  # 匿名不能自定义排除项
            "tool-availability-degradation",
            repeat_count=1,
            role=ROLE_ANONYMOUS,
            owner_excluded_tools=["weather.get_forecast"],
        )


# ── B2/B3 统一底座与治理开关 ────────────────────────────────────────────────


_FIXTURES = [
    {
        "tool": "weather.get_forecast",
        "match_mode": "subset",
        "match_arguments": {"location": "上海"},
        "status": "success",
        "result": {"forecast": "多云,25℃", "location": "上海"},
        "fixture_id": "fx-weather-1",
        "fixture_version": 1,
    }
]
_VISIBLE = ("weather.get_forecast", "web.search")


@pytest.mark.asyncio
async def test_governance_variants_share_same_loop_tools_and_input():
    """两个治理变体经同一原生循环、同一工具目录与同一输入运行。"""
    plan = plan_template_batch("governance-on-off", repeat_count=1)
    result = await run_template_batch(
        plan,
        message="上海今天天气如何?",
        visible_tools=_VISIBLE,
        llm=FakeChatModel([
            _call("weather.get_forecast", {"location": "上海"}, "c1"),
            AIMessage(content="上海今天多云,25℃。"),
        ] * 2),  # 两个变体各消耗一组(调用+回答)
        fixtures=_FIXTURES,
    )
    assert result["template_id"] == "governance-on-off"
    variants = {row["variant_label"]: row for row in result["runs"]}
    assert set(variants) == {"off", "standard"}
    for row in variants.values():
        # 证据口径:visible_tools 为实际装载集合(all 模式 = eligible,按稳定名排序)
        assert sorted(row["visible_tools"]) == sorted(_VISIBLE)
        assert row["tool_calls"][0]["toolName"] == "weather.get_forecast"  # 相同输入→相同调用
        assert row["config_hash"]
    assert variants["off"]["governance_profile"] == GOVERNANCE_OFF
    assert variants["standard"]["governance_profile"] == GOVERNANCE_STANDARD
    # 正常只读调用不触发旁路;两组 config_hash 因治理档位而不同
    assert variants["off"]["config_hash"] != variants["standard"]["config_hash"]


@pytest.mark.asyncio
async def test_governance_off_bypass_visible_but_mock_only():
    """治理关闭:权限拦截被旁路(记录 bypassed 与原规则),但只执行 Mock。"""
    record = await run_native_agent(
        run_config=TEMPLATES["governance-on-off"].base_config.with_overrides(
            {"governance_profile": GOVERNANCE_OFF}
        ),
        message="帮我查天气",
        visible_tools=("weather.get_forecast",),
        llm=FakeChatModel([
            _call("weather.get_forecast", {"location": "上海"}, "c1"),
            AIMessage(content="上海多云。"),
        ]),
        fixtures=_FIXTURES,
        authenticated=False,  # 游客:weather 工具无需登录,但用受限工具验证旁路
        user_id="guest",
    )
    # 正常只读工具在 off 档没有会被触发的规则 → 无旁路事件
    assert record.bypassed_event_count == 0


@pytest.mark.asyncio
async def test_governance_off_bypasses_permission_for_restricted_tool():
    """off 档:需登录工具仍可见,权限规则被旁路并记录,Mock 仍执行。"""
    llm = FakeChatModel([
        _call("document.summarize", {"path": "/tmp/report.md"}, "c1"),
        AIMessage(content="已总结。"),
    ])
    fixtures = [
        {
            "tool": "document.summarize",
            "match_mode": "subset",
            "match_arguments": {"path": "/tmp/report.md"},
            "status": "success",
            "result": {"summary": "报告摘要"},
            "fixture_id": "fx-doc-1",
            "fixture_version": 1,
        }
    ]
    record = await run_native_agent(
        run_config=TEMPLATES["governance-on-off"].base_config.with_overrides(
            {"governance_profile": GOVERNANCE_OFF}
        ),
        message="总结这份报告",
        visible_tools=("document.summarize",),
        llm=llm,
        fixtures=fixtures,
        authenticated=False,  # 游客调用需登录工具:standard 会拦,off 旁路
        user_id="guest",
    )
    executed = [row for row in record.tool_calls if row["toolName"] == "document.summarize"]
    assert executed, "off 档旁路后 Mock 执行应发生"
    bypassed = [row for row in record.audits if row.get("bypassed")]
    assert bypassed, "旁路事件必须可见"
    assert any("G3-AUTH-001" in str(rule.get("rule_id")) for row in bypassed for rule in row["bypassed_rules"])
    assert record.bypassed_event_count >= 1
    # Mock-only:执行返回带 simulated 标记(recorder 明细行的 resultSummary)
    assert executed[0]["status"] == "SUCCESS" and executed[0]["fixtureHit"] is True
    assert executed[0]["resultSummary"].get("simulated") is True
    assert executed[0]["callId"] == "c1" and executed[0]["modelCallSequence"] == 1


@pytest.mark.asyncio
async def test_governance_standard_blocks_restricted_tool_for_guest():
    record = await run_native_agent(
        run_config=TEMPLATES["governance-on-off"].base_config,  # standard
        message="总结这份报告",
        visible_tools=("document.summarize",),
        llm=FakeChatModel([
            _call("document.summarize", {"path": "/tmp/report.md"}, "c1"),
            AIMessage(content="抱歉,我无权访问该工具。"),
        ]),
        fixtures=[],
        authenticated=False,
        user_id="guest",
    )
    # standard 档拦截:保留 DENIED 明细行(无真实执行,fixture_hit=false)
    denied = [row for row in record.tool_calls if row["toolName"] == "document.summarize"]
    assert denied and all(row["status"] == "DENIED" and row["fixtureHit"] is False for row in denied)
    assert any(row.get("audit_code") == "AUTHENTICATION_REQUIRED" for row in record.audits)


# ── B4 写操作确认 ──────────────────────────────────────────────────────────


def _write_catalog() -> ToolCatalog:
    catalog = ToolCatalog()
    catalog.register(
        ToolCard(
            name="mail.send",
            description="发送邮件(Mock,需确认)",
            parameters={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
            read_only=True,  # 目录只读红线;写意图由 side_effect/requires_confirmation 表达
            required_scope=["authenticated"],
            side_effect="external_action",
            requires_confirmation=True,
        )
    )
    return catalog


def _mw(catalog: ToolCatalog, *, provider=None, store=None, profile="standard") -> GovernanceMiddleware:
    # 闭环:提供方与中间件必须共享同一权威存储(仅字段自洽的外部记录无效)
    shared = store or getattr(provider, "store", None) or ConfirmationStore()
    return GovernanceMiddleware(
        catalog,
        context=GuardrailContext(
            run_id="run-cfm",
            authenticated_user_id="owner-1",
            read_only=True,
            max_tool_calls=6,
            governance_profile=profile,
            authorized_capabilities=frozenset(),
            max_calls_per_tool=2,
        ),
        confirmation_provider=provider,
        confirmation_store=shared,
    )


async def _mock_send(_name: str, arguments: dict) -> dict:
    return {"sent": True, "to": arguments.get("to"), "simulated": True}


_ARGS = {"to": "a@ex.com", "subject": "hi", "body": "hello"}


@pytest.mark.asyncio
async def test_missing_confirmation_rejected_before_execution():
    mw = _mw(_write_catalog(), provider=DenyAllConfirmationProvider())
    result = await mw.invoke(
        name="mail.send",
        arguments=_ARGS,
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert result.allowed is False
    assert result.rejection.audit_code == AUDIT_CONFIRMATION_REQUIRED  # 与 G2 只读码分开
    assert result.audit.status == "REJECTED"


@pytest.mark.asyncio
async def test_valid_confirmation_allows_bound_mock_write_only():
    provider = AutoGrantConfirmationProvider()
    mw = _mw(_write_catalog(), provider=provider)
    first = await mw.invoke(
        name="mail.send",
        arguments=_ARGS,
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert first.allowed is True
    assert first.observation.data["simulated"] is True
    # 确认单次消费:同一绑定的第二次调用不再授予 → CONFIRMATION_REQUIRED
    second = await mw.invoke(
        name="mail.send",
        arguments=_ARGS,
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert second.allowed is False
    assert second.rejection.audit_code == AUDIT_CONFIRMATION_REQUIRED


@pytest.mark.asyncio
async def test_changed_arguments_invalidate_old_confirmation():
    store = ConfirmationStore()
    record = store.create(run_id="run-cfm", tool_name="mail.send", arguments=_ARGS, actor="owner")
    mw = _mw(_write_catalog(), provider=lambda *_a, **_k: record, store=store)  # 权威存储中的旧确认
    result = await mw.invoke(
        name="mail.send",
        arguments={**_ARGS, "body": "changed"},
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert result.allowed is False
    assert result.rejection.audit_code == AUDIT_CONFIRMATION_ARGUMENTS_MISMATCH


@pytest.mark.asyncio
async def test_expired_and_cross_run_confirmations_rejected():
    expired_store = ConfirmationStore(ttl_seconds=0)
    expired = expired_store.create(run_id="run-cfm", tool_name="mail.send", arguments=_ARGS, actor="owner")
    mw = _mw(_write_catalog(), provider=lambda *_a, **_k: expired, store=expired_store)
    result = await mw.invoke(
        name="mail.send",
        arguments=_ARGS,
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert result.rejection.audit_code == AUDIT_CONFIRMATION_EXPIRED

    other_store = ConfirmationStore()
    other_run = other_store.create(run_id="run-other", tool_name="mail.send", arguments=_ARGS, actor="owner")
    mw2 = _mw(_write_catalog(), provider=lambda *_a, **_k: other_run, store=other_store)
    result2 = await mw2.invoke(
        name="mail.send",
        arguments=_ARGS,
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert result2.rejection.audit_code == AUDIT_CONFIRMATION_RUN_MISMATCH


@pytest.mark.asyncio
async def test_forged_confirmation_not_in_authoritative_store_rejected():
    """闭环:仅字段自洽、不在权威存储中的确认对象无效(CONFIRMATION_INVALID)。"""
    forged = ConfirmationStore().create(run_id="run-cfm", tool_name="mail.send", arguments=_ARGS, actor="attacker")
    mw = _mw(_write_catalog(), provider=lambda *_a, **_k: forged)  # 中间件持另一份权威存储
    result = await mw.invoke(
        name="mail.send",
        arguments=_ARGS,
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert result.allowed is False
    assert result.rejection.audit_code == AUDIT_CONFIRMATION_INVALID


@pytest.mark.asyncio
async def test_async_confirmation_provider_supported():
    """提供方返回协程时正确等待,并按权威存储校验。"""
    store = ConfirmationStore()

    async def async_provider(run_id, tool_name, arguments):
        return store.create(run_id=run_id, tool_name=tool_name, arguments=arguments, actor="owner")

    mw = _mw(_write_catalog(), provider=async_provider, store=store)
    result = await mw.invoke(
        name="mail.send",
        arguments=_ARGS,
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert result.allowed is True
    assert result.observation.data["simulated"] is True


def test_arguments_hash_stable_to_key_order():
    assert hash_arguments({"a": 1, "b": 2}) == hash_arguments({"b": 2, "a": 1})
    assert hash_arguments({"a": 1}) != hash_arguments({"a": 2})


@pytest.mark.asyncio
async def test_governance_off_write_still_mock_only_and_bypassed():
    """off 档写调用:确认被旁路(记录规则),但执行器仍是 Mock。"""
    mw = _mw(_write_catalog(), profile=GOVERNANCE_PROFILE_OFF)  # 无提供方
    result = await mw.invoke(
        name="mail.send",
        arguments=_ARGS,
        loaded_names={"mail.send"},
        granted_scopes={"authenticated"},
        authenticated=True,
        executor=_mock_send,
    )
    assert result.allowed is True
    assert result.observation.data["simulated"] is True
    assert result.audit.bypassed is True
    codes = {rule.get("audit_code") for rule in result.audit.bypassed_rules}
    assert AUDIT_CONFIRMATION_REQUIRED in codes  # 原本会触发的确认规则被记录


# ── B5 治理指标 ────────────────────────────────────────────────────────────


def _probe(probe_id: str) -> GovernanceProbeCase:
    return next(probe for probe in GOVERNANCE_PROBES if probe.probe_id == probe_id)


def test_metrics_distinguish_correct_false_and_bypassed():
    correct = evaluate_governance_probe(
        _probe("permission-denied"),
        _observation(
            _probe("permission-denied"),
            blocked=True,
            audits=[{"audit_code": "AUTHENTICATION_REQUIRED", "status": "REJECTED", "bypassed": False}],
        ),
    )
    assert correct["correct_block"] is True
    false_positive = evaluate_governance_probe(
        _probe("read-normal"),
        _observation(
            _probe("read-normal"),
            blocked=True,
            audits=[{"audit_code": "SCOPE_DENIED", "status": "REJECTED", "bypassed": False}],
        ),
    )
    assert false_positive["false_block"] is True
    bypassed = evaluate_governance_probe(
        _probe("permission-denied"),
        _observation(
            _probe("permission-denied"),
            blocked=False,
            executed=True,
            audits=[{"audit_code": None, "status": "SUCCESS", "bypassed": True,
                     "bypassed_rules": [{"rule_id": "G3-AUTH-001", "audit_code": "AUTHENTICATION_REQUIRED",
                                          "reason": "该工具仅机主可调用"}]}],
        ),
    )
    assert bypassed["missed_block"] is True
    assert bypassed["unauthorized_mock_execution"] == 1
    assert bypassed["bypassed_event_count"] == 1
    summary = summarize_governance_metrics([correct, false_positive, bypassed])
    assert summary["interception_recall"] == 0.5  # 应拦截 2 例,正确 1 例
    assert summary["false_interception_rate"] == 1.0
    assert summary["unauthorized_mock_executions"] == 1
    assert summary["bypassed_event_count"] == 1


def _observation(probe, *, blocked, executed=False, audits=(), confirmation=None, stop_reason=""):
    from bdlh_runtime.experiments.governance_metrics import GovernanceRunObservation

    return GovernanceRunObservation(
        probe_id=probe.probe_id,
        blocked=blocked,
        executed=executed,
        audits=tuple(audits),
        valid_confirmation_used=confirmation,
        rejection_then_final=bool(blocked) and stop_reason == "FINAL_ANSWER",
        total_tool_calls=max(1, len(audits)),
        audited_calls=len(audits),
    )


def test_unconfirmed_write_mock_execution_counted():
    write_probe = _probe("confirmation-write")
    row = evaluate_governance_probe(
        write_probe,
        _observation(write_probe, blocked=False, executed=True,
                     audits=[{"audit_code": None, "status": "SUCCESS", "bypassed": False}]),
    )
    assert row["unconfirmed_write_mock_execution"] == 1
    confirmed = evaluate_governance_probe(
        write_probe,
        _observation(write_probe, blocked=False, executed=True, confirmation=True,
                     audits=[{"audit_code": None, "status": "SUCCESS", "bypassed": False}]),
    )
    assert confirmed["unconfirmed_write_mock_execution"] == 0


def test_governance_metrics_from_real_loop_run():
    """从统一执行器的一次真实(标准档)运行审计直接构造指标。"""
    import asyncio

    async def scenario() -> dict:
        record = await run_native_agent(
            run_config=TEMPLATES["governance-on-off"].base_config,
            message="总结这份报告",
            visible_tools=("document.summarize",),
            llm=FakeChatModel([
                _call("document.summarize", {"path": "/tmp/report.md"}, "c1"),
                AIMessage(content="抱歉,当前身份无权调用该工具。"),
            ]),
            fixtures=[],
            authenticated=False,
            user_id="guest",
        )
        return governance_metrics_for_run(
            record.audits,
            probe=_probe("permission-denied"),
            executed=False,
            stop_reason=record.stop_reason,
        )

    row = asyncio.run(scenario())
    assert row["correct_block"] is True
    assert row["audit_completeness"] == 1.0


def test_probe_coverage_six_scenarios():
    ids = {probe.probe_id for probe in GOVERNANCE_PROBES}
    assert {
        "read-normal",
        "permission-denied",
        "confirmation-write",
        "invalid-arguments",
        "budget-exceeded",
        "tool-result-injection",
    } <= ids


# ── 固定工件哈希(批次内 Mock 冻结口径) ─────────────────────────────────────


def test_fixture_content_hash_stable():
    assert fixture_content_hash(_FIXTURES) == fixture_content_hash(_FIXTURES)
    changed = [dict(_FIXTURES[0], result={"forecast": "晴"})]
    assert fixture_content_hash(_FIXTURES) != fixture_content_hash(changed)
