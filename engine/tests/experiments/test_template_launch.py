"""模板发起闭环与修复回归测试(评审阻断项 1–5)。

- 阻断1:POST /api/v1/template-batches/plan(预估)与发起链路、匿名模板任务;
- 阻断2:all 模式不扩大执行授权;
- 阻断3:运行证据记录实际装载集合;
- 阻断5:模板运行落库载荷与确认记录载荷(只构建,不执行 SQL)。

全部使用 FakeChatModel / 内存仓储 / 依赖覆盖,不调用真实 LLM。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.experiments.comparison import ComparisonCase
from bdlh_runtime.experiments.job_store import JobStore
from bdlh_runtime.experiments.judge import CallRelationSpec
from bdlh_runtime.experiments.public_service import AnonymousJobService, PublicTestError
from bdlh_runtime.experiments.quota import PublicQuotaConfig
from bdlh_runtime.experiments.templates import plan_template_batch
from bdlh_runtime.guardrails.confirmations import (
    CONFIRMATION_STATUS_USED,
    ConfirmationStore,
    build_confirmation_upsert,
)


class FakeChatModel:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0

    def bind_tools(self, tools, **_kwargs):
        return self

    async def ainvoke(self, messages, **_kwargs):
        assert self._index < len(self._responses), "FakeChatModel 响应已耗尽"
        item = self._responses[self._index]
        self._index += 1
        return item

    async def astream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


def _call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _case() -> ComparisonCase:
    return ComparisonCase(
        case_id="cmp-tpl-01",
        case_version=1,
        title="模板用例",
        message="上海今天天气如何?",
        scene="general",
        allowed_tools=("weather.get_forecast", "web.search"),
        default_visible_tools=("weather.get_forecast", "web.search"),
        fixture_set_id="fixture-v1",
        call_relation=CallRelationSpec(),
        conditions={
            "mock_fixtures": [
                {
                    "tool": "weather.get_forecast",
                    "match_mode": "subset",
                    "match_arguments": {"location": "上海"},
                    "status": "success",
                    "result": {"forecast": "多云 25℃"},
                    "fixture_id": "fx-w",
                    "fixture_version": 1,
                }
            ]
        },
    )


# ── 阻断1:预估端点 ─────────────────────────────────────────────────────────


@pytest.fixture()
def owner_client():
    from fastapi.testclient import TestClient

    import bdlh_runtime.run_api as run_api

    client = TestClient(run_api.app)
    client.app.dependency_overrides[run_api.require_login] = lambda: {"username": "owner"}
    yield client
    client.app.dependency_overrides.clear()


def test_template_plan_endpoint_returns_exact_run_count(owner_client):
    response = owner_client.post(
        "/api/v1/template-batches/plan",
        json={"template_id": "governance-on-off", "repeat_count": 3},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_count"] == 6
    assert {run["variant_label"] for run in payload["runs"]} == {"off", "standard"}
    assert all(run["config_hash"] for run in payload["runs"])
    assert payload["fixed_conditions"]["independent_variable"] == ["governance_profile"]
    assert payload["fixed_conditions_hash"]
    assert "治理档位" in payload["purpose"]


def test_template_plan_endpoint_rejects_invalid_requests(owner_client):
    bad_repeat = owner_client.post(
        "/api/v1/template-batches/plan",
        json={"template_id": "governance-on-off", "repeat_count": 9},
    )
    assert bad_repeat.status_code == 400
    unknown = owner_client.post(
        "/api/v1/template-batches/plan",
        json={"template_id": "no-such-template", "repeat_count": 1},
    )
    assert unknown.status_code == 400
    # 匿名不可用的高级字段同样被拒(所有者角色 + 非白名单路径)
    rogue_advanced = owner_client.post(
        "/api/v1/template-batches/plan",
        json={"template_id": "governance-on-off", "repeat_count": 1,
              "advanced": {"context.token_budget": 999}},
    )
    assert rogue_advanced.status_code == 400


def test_template_plan_endpoint_temperature_needs_env_llm(owner_client, monkeypatch):
    """环境无 LLM 配置 → 能力描述不支持温度 → 模板批次预估被拒(诚实失败)。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    response = owner_client.post(
        "/api/v1/template-batches/plan",
        json={"template_id": "temperature-stability", "repeat_count": 3},
    )
    assert response.status_code == 400
    assert "温度" in response.json()["detail"]


def test_template_launch_endpoint_validates_before_batch(owner_client, monkeypatch):
    """发起入口在创建批次前完成校验:上下文模板/未知用例/context_only 均拒绝。"""
    from bdlh_runtime.experiments import public_case_repository

    monkeypatch.setattr(
        public_case_repository, "get_case_repository", lambda: _MemoryRepo([_case()])
    )
    context_template = owner_client.post(
        "/api/v1/template-batches",
        json={"template_id": "context-strategy-comparison", "repeat_count": 1, "case_id": "cmp-tpl-01"},
    )
    assert context_template.status_code == 400
    unknown_case = owner_client.post(
        "/api/v1/template-batches",
        json={"template_id": "governance-on-off", "repeat_count": 1, "case_id": "no-such-case"},
    )
    assert unknown_case.status_code == 400
    context_only = owner_client.post(
        "/api/v1/template-batches",
        json={"template_id": "governance-on-off", "repeat_count": 1, "case_id": "cmp-tpl-01",
              "context_only": True},
    )
    assert context_only.status_code == 400


class _MemoryRepo:
    def __init__(self, cases):
        self._cases = cases

    def get_public_case(self, case_id):
        return next((case for case in self._cases if case.case_id == case_id), None)


# ── 阻断1:执行链路(内部函数 + Fake LLM,不触发真实模型) ──────────────────


def test_execute_template_batch_wiring_with_fake_llm():
    import bdlh_runtime.run_api as run_api

    plan = plan_template_batch("governance-on-off", repeat_count=1)
    report = run_api._execute_template_batch(
        plan, _case(), model="fake-model",
        llm=FakeChatModel([
            _call("weather.get_forecast", {"location": "上海"}, "c1"),
            AIMessage(content="上海今天多云,25℃。"),
        ] * 2),
    )
    assert report["template_id"] == "governance-on-off"
    assert len(report["runs"]) == 2
    assert {row["governance_profile"] for row in report["runs"]} == {"off", "standard"}
    assert all(row["config_hash"] for row in report["runs"])


def test_template_run_model_config_carries_template_fields():
    import bdlh_runtime.run_api as run_api

    plan = plan_template_batch("governance-on-off", repeat_count=1)
    row = {
        "variant_label": "off",
        "repeat_index": 0,
        "config_hash": "hash-abc",
        "governance_profile": "off",
        "run_config": {"execution_engine": "native-tool-calling", "tool_delivery": "all",
                       "governance_profile": "off", "config_hash": "hash-abc"},
        "tool_schema_hash": "schema-hash",
        "eligible_catalog_hash": "eligible-hash",
    }
    config = run_api.template_run_model_config(plan, row, fixture_set_id="fixture-v1")
    assert config["templateId"] == "governance-on-off"
    assert config["templateVersion"] == 1
    assert config["configHash"] == "hash-abc"
    assert config["perRunConfig"]["execution_engine"] == "native-tool-calling"
    assert config["fixtureSetId"] == "fixture-v1"
    assert config["experimentDefinitionVersion"] == "run-config-v2"


def test_persist_template_runs_builds_create_run_payloads(monkeypatch):
    """落库链路:每次运行一条 create_run + complete_run(替身 DataClient 记录调用)。"""
    import bdlh_runtime.run_api as run_api

    plan = plan_template_batch("governance-on-off", repeat_count=1)
    report = run_api._execute_template_batch(
        plan, _case(), model="fake-model",
        llm=FakeChatModel([
            _call("weather.get_forecast", {"location": "上海"}, "c1"),
            AIMessage(content="上海今天多云,25℃。"),
        ] * 2),
    )
    created: list[dict] = []
    completed: list[tuple[str, dict]] = []

    class FakeData:
        def create_run(self, payload):
            created.append(payload)
            return f"run-{len(created)}"

        def complete_run(self, run_id, payload, *, status, error_category=None):
            completed.append((run_id, payload))

    run_api._persist_template_runs(FakeData(), "batch-1", plan, _case(), report)
    assert len(created) == 2
    assert all(payload["batchId"] == "batch-1" for payload in created)
    assert all(payload["agentMode"] == "native-tool-calling" for payload in created)
    assert {payload["modelConfig"]["variantLabel"] for payload in created} == {"off", "standard"}
    assert all(payload["modelConfig"]["templateId"] == "governance-on-off" for payload in created)
    assert len(completed) == 2
    assert all(row[1]["config_hash"] for row in completed)


# ── 阻断1:匿名模板任务(服务层,替身执行器) ────────────────────────────────


def _fake_template_executor(job, *, should_stop=lambda: False):
    return {
        "template_id": job.template_id,
        "template_version": job.template_version,
        "classification": "formal-single-variable",
        "independent_variable": ["governance_profile"],
        "run_count": len(job.units),
        "fixed_conditions_hash": job.template_plan_hash,
        "by_variant": {"off": {"total_runs": 1}, "standard": {"total_runs": 1}},
        "runs": [
            {"run_id": unit.unit_id, "unit_id": unit.unit_id, "variant_label": unit.context_variant,
             "repeat_index": unit.repeat_index, "answer": "ok", "tool_calls": [],
             "stop_reason": "FINAL_ANSWER", "actual_agent_steps": 1, "duration_ms": 5,
             "validity": "VALID"}
            for unit in job.units
        ],
    }


def test_anonymous_template_job_creates_and_applies(tmp_path):
    store = JobStore(tmp_path / "jobs")
    service = AnonymousJobService(
        store,
        case_repository=_MemoryRepo([_case()]),
        quota=PublicQuotaConfig(),
        template_executor=_fake_template_executor,
        thread_factory=lambda target: (target(), None)[1],  # 同步执行
    )
    job = service.create_job(
        {
            "test_type": "COMPARISON_CASE",
            "template_id": "governance-on-off",
            "case_id": "cmp-tpl-01",
            "repeat_count": 1,
        },
        anonymous_id_hash="sha256:anon",
    )
    assert job.template_id == "governance-on-off"
    assert job.execution_scope == "template-batch"
    assert job.publishable is False
    assert len(job.units) == 2
    assert {u.agent_mode_id for u in job.units} == {"native-tool-calling"}
    # 同步线程工厂已执行完毕;create_job 返回的是执行前快照,状态从存储重读
    reloaded = store.get(job.job_id)
    assert reloaded is not None and reloaded.status == "COMPLETE"
    assert reloaded.result["template_id"] == "governance-on-off"
    assert reloaded.result["by_variant"]
    assert all(u.status == "COMPLETE" for u in reloaded.units)


def test_anonymous_template_job_rejects_owner_only_or_unknown(tmp_path):
    store = JobStore(tmp_path / "jobs")
    service = AnonymousJobService(
        store,
        case_repository=_MemoryRepo([_case()]),
        quota=PublicQuotaConfig(),
        template_executor=_fake_template_executor,
        thread_factory=lambda target: None,
    )
    with pytest.raises(PublicTestError):
        service.create_job(
            {"test_type": "COMPARISON_CASE", "template_id": "temperature-stability",
             "case_id": "cmp-tpl-01", "repeat_count": 3},  # 匿名不可用 + 无能力
            anonymous_id_hash="sha256:anon",
        )
    with pytest.raises(PublicTestError):
        service.create_job(
            {"test_type": "COMPARISON_CASE", "template_id": "governance-on-off",
             "case_id": "cmp-tpl-01", "repeat_count": 1,
             "advanced": {"model.seed_requested": 1}},  # 匿名不能提交高级设置(未知字段)
            anonymous_id_hash="sha256:anon",
        )
    with pytest.raises(PublicTestError):
        service.create_job(
            {"test_type": "COMPARISON_CASE", "template_id": "no-such-template",
             "case_id": "cmp-tpl-01", "repeat_count": 1},
            anonymous_id_hash="sha256:anon",
        )


def test_anonymous_template_preset_flow(tmp_path):
    store = JobStore(tmp_path / "jobs")
    service = AnonymousJobService(
        store,
        case_repository=_MemoryRepo([_case()]),
        quota=PublicQuotaConfig(),
        template_executor=_fake_template_executor,
        thread_factory=lambda target: (target(), None)[1],
    )
    job = service.create_job(
        {"test_type": "COMPARISON_CASE", "template_id": "tool-availability-degradation",
         "case_id": "cmp-tpl-01", "repeat_count": 1, "preset_id": "remove-preferred"},
        anonymous_id_hash="sha256:anon",
    )
    assert job.template_preset_id == "remove-preferred"
    assert len(job.units) == 1


# ── 阻断2:all 模式不扩大执行授权 ───────────────────────────────────────────


def test_all_mode_grants_scene_scopes_not_tool_union():
    from bdlh_runtime.engine.loader import ToolLoader
    from bdlh_runtime.experiments.template_runner import build_template_catalog

    catalog, _ = build_template_catalog(("weather.get_forecast", "web.search", "document.summarize"))
    all_loader = ToolLoader(catalog, tool_loading="all")
    scoped_loader = ToolLoader(catalog, tool_loading="scoped")
    # 可见性:all 对游客也展示需登录工具(可见≠授权,执行由 G3 裁决)
    assert {card.name for card in all_loader.load_for_turn("general", authenticated=False)} == {
        "weather.get_forecast", "web.search", "document.summarize"
    }
    # 执行授权口径一致:all 不合并工具 scope
    assert all_loader.granted_scopes("general", authenticated=False) == scoped_loader.granted_scopes(
        "general", authenticated=False
    )
    assert "authenticated" not in all_loader.granted_scopes("general", authenticated=False)
    assert "authenticated" in all_loader.granted_scopes("general", authenticated=True)


@pytest.mark.asyncio
async def test_all_mode_restricted_tool_visible_but_blocked_for_guest():
    """需登录工具在 all 模式下可见,但游客执行被 G3 拦截(可见≠授权)。"""
    from bdlh_runtime.experiments.template_runner import run_native_agent
    from bdlh_runtime.experiments.templates import TEMPLATES

    record = await run_native_agent(
        run_config=TEMPLATES["governance-on-off"].base_config,
        message="总结报告",
        visible_tools=("document.summarize",),
        llm=FakeChatModel([
            _call("document.summarize", {"path": "/tmp/r.md"}, "c1"),
            AIMessage(content="无权调用。"),
        ]),
        fixtures=[],
        authenticated=False,
        user_id="guest",
    )
    assert "document.summarize" in record.visible_tools  # 对模型可见
    assert any(row.get("audit_code") == "AUTHENTICATION_REQUIRED" for row in record.audits)  # 执行被拦
    assert not [row for row in record.tool_calls if row["tool"] == "document.summarize"]


# ── 阻断3:证据记录实际装载集合 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_records_actual_loaded_tools_search_mode():
    from bdlh_runtime.experiments.template_runner import run_native_agent
    from bdlh_runtime.experiments.templates import TEMPLATES

    class BigramEncoder:
        def encode(self, texts):
            return [self._vec(t) for t in texts]

        @staticmethod
        def _vec(text):
            vec = [0.0] * 4096
            cleaned = text.lower()
            for i in range(max(0, len(cleaned) - 1)):
                vec[hash(cleaned[i : i + 2]) % 4096] += 1.0
            return vec

    record = await run_native_agent(
        run_config=TEMPLATES["tool-delivery-comparison"].base_config.with_overrides(
            {"tool_delivery": "search", "tools.search_top_k": 3}
        ),
        message="查上海天气",
        visible_tools=("weather.get_forecast", "web.search", "calculator.evaluate", "document.summarize"),
        llm=FakeChatModel([
            _call("search_tools", {"query": "查询天气 预报", "top_k": 3}, "c0"),
            _call("weather.get_forecast", {"location": "上海"}, "c1"),
            AIMessage(content="上海多云。"),
        ]),
        fixtures=[{
            "tool": "weather.get_forecast", "match_mode": "subset",
            "match_arguments": {"location": "上海"}, "status": "success",
            "result": {"forecast": "多云"}, "fixture_id": "fx", "fixture_version": 1,
        }],
        encoder=BigramEncoder(),
        timeout_seconds=30,
    )
    # 证据 = 实际装载(search_tools + 命中缓存),不是初始完整列表
    assert set(record.visible_tools) == {"search_tools", "weather.get_forecast"}
    assert record.tool_schema_tokens > 0
    assert record.eligible_catalog_hash  # 初始完整目录另记


@pytest.mark.asyncio
async def test_evidence_records_actual_loaded_tools_exclusion():
    from bdlh_runtime.experiments.template_runner import run_native_agent
    from bdlh_runtime.experiments.templates import TEMPLATES

    record = await run_native_agent(
        run_config=TEMPLATES["governance-on-off"].base_config.with_overrides(
            {"tools.excluded_tools": ["weather.get_forecast"]}
        ),
        message="查上海天气",
        visible_tools=("weather.get_forecast", "web.search"),
        llm=FakeChatModel([
            _call("web.search", {"query": "上海 天气"}, "c1"),
            AIMessage(content="根据检索:上海多云。"),
        ]),
        fixtures=[{
            "tool": "web.search", "match_mode": "subset",
            "match_arguments": {"query": "上海 天气"}, "status": "success",
            "result": {"results": ["上海多云"]}, "fixture_id": "fx2", "fixture_version": 1,
        }],
    )
    assert record.visible_tools == ["web.search"]  # 排除项不出现在证据里
    assert "weather.get_forecast" not in record.visible_tools


@pytest.mark.asyncio
async def test_evidence_text_only_run_still_records_bound_tools():
    from bdlh_runtime.experiments.template_runner import run_native_agent
    from bdlh_runtime.experiments.templates import TEMPLATES

    record = await run_native_agent(
        run_config=TEMPLATES["governance-on-off"].base_config,
        message="直接回答即可",
        visible_tools=("web.search",),
        llm=FakeChatModel([AIMessage(content="好的,这是回答。")]),
        fixtures=[],
    )
    # 直答路径本轮仍发生了 bind_tools(模型看得到 Schema)→ 证据如实记录绑定集合
    assert record.visible_tools == ["web.search"]
    assert record.tool_schema_tokens > 0
    assert record.stop_reason == "FINAL_ANSWER"


# ── 阻断5:确认记录持久化载荷(只构建,不执行) ─────────────────────────────


def test_confirmation_upsert_payload_matches_table_columns():
    store = ConfirmationStore()
    record = store.create(run_id="run-1", tool_name="mail.send",
                          arguments={"to": "a@x.com"}, actor="owner")
    payload = build_confirmation_upsert(record)
    assert set(payload) == {"id", "run_id", "tool_name", "arguments_hash", "actor",
                            "expires_at", "status", "consumed_at"}
    assert payload["id"] == record.confirmation_id
    assert payload["status"] == "GRANTED"
    assert payload["consumed_at"] is None
    used = store.consume(record)
    consumed = build_confirmation_upsert(used, consumed_at="2026-08-26T00:00:00+00:00")
    assert consumed["status"] == CONFIRMATION_STATUS_USED
    assert consumed["consumed_at"] == "2026-08-26T00:00:00+00:00"


# ── 压缩方法对照模板:所有者专属,2 变体,context_only 允许 ─────────────────


def test_method_comparison_template_owner_only_and_two_runs():
    """压缩方法对照模板:仅所有者可发起;计划 2 个运行;context_only 允许。"""
    from bdlh_runtime.experiments.templates import (
        ROLE_ANONYMOUS,
        ROLE_OWNER,
        TemplatePlanError,
        plan_template_batch,
    )

    with pytest.raises(TemplatePlanError, match="不对匿名用户开放"):
        plan_template_batch("compression-method-comparison", repeat_count=1, role=ROLE_ANONYMOUS)
    plan = plan_template_batch("compression-method-comparison", repeat_count=1, role=ROLE_OWNER)
    assert plan.run_count == 2
    strategies = {run.run_config.context_strategy for run in plan.runs}
    assert strategies == {"budgeted", "budgeted-llm"}
    context_only_plan = plan_template_batch(
        "compression-method-comparison", repeat_count=1, role=ROLE_OWNER, context_only=True
    )
    assert context_only_plan.context_only is True
    assert context_only_plan.runs == ()


# ── 温度模板修复:逐运行模型客户端 + 实际生效参数 ──────────────────────────


class TempFakeModel(FakeChatModel):
    """带 temperature 属性的 Fake(供 applied_model_params 读回)。"""

    def __init__(self, responses, temperature):
        super().__init__(responses)
        self.temperature = temperature


@pytest.mark.asyncio
async def test_temperature_template_builds_distinct_llm_per_run(monkeypatch):
    """四种温度 → 四个独立模型实例,各自携带自己的温度;证据逐运行记录。

    回归背景:批次执行曾把一个默认 0.1 的实例交给全部运行,导致
    「记录显示四种温度、实际请求全是 0.1」。
    """
    from bdlh_runtime.experiments import template_runner
    from bdlh_runtime.experiments.templates import plan_template_batch
    from bdlh_runtime.infra.llm import ModelCapability

    captured: list[dict] = []

    def fake_factory(run_config, *, model=None):
        entry = {
            "temperature_requested": run_config.model.temperature_requested,
            "instance": object(),  # 每次调用必然是新对象
        }
        captured.append(entry)
        return TempFakeModel(
            [
                _call("weather.get_forecast", {"location": "上海"}, "c1"),
                AIMessage(content="上海多云。"),
            ],
            temperature=run_config.model.temperature_effective,
        )

    monkeypatch.setattr(template_runner, "build_llm_for_config", fake_factory)
    plan = plan_template_batch(
        "temperature-stability", repeat_count=3, model_capability=ModelCapability(supports_temperature=True)
    )
    result = await template_runner.run_template_batch(
        plan, message="上海天气", visible_tools=("weather.get_forecast",), llm=None,
        fixtures=[{
            "tool": "weather.get_forecast", "match_mode": "subset",
            "match_arguments": {"location": "上海"}, "status": "success",
            "result": {"forecast": "多云"}, "fixture_id": "fx", "fixture_version": 1,
        }],
    )
    assert len(captured) == 12  # 4 变体 × 3 次:每次运行独立构建
    assert {row["temperature_requested"] for row in captured} == {0.0, 0.1, 0.3, 0.7}
    assert len({id(row["instance"]) for row in captured}) == 12  # 全部是不同实例
    # 证据:每次运行的 applied 温度与该变体配置的生效温度一致
    expected_by_label = {p.variant_label: p.run_config.model.temperature_effective for p in plan.runs}
    for row in result["runs"]:
        assert row["applied_model_params"]["temperature"] == expected_by_label[row["variant_label"]]
    assert {row["applied_model_params"]["temperature"] for row in result["runs"]} == {0.0, 0.1, 0.3, 0.7}
    # 四个变体配置哈希互不相同(温度确实进入配置)
    assert len({row["config_hash"] for row in result["runs"]}) == 4


def test_create_llm_passes_frozen_params_to_sdk(monkeypatch):
    """temperature/max_output_tokens/parallel_tool_calls 真实进入 SDK 构造。"""
    from bdlh_runtime.infra.llm import create_llm

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    llm = create_llm(
        api_key="test-key", base_url="http://localhost:9", model="m",
        temperature=0.7, max_output_tokens=1200, parallel_tool_calls=False,
    )
    assert llm is not None
    assert llm.temperature == 0.7
    assert llm.max_tokens == 1200
    assert llm.model_kwargs.get("parallel_tool_calls") is False

    from bdlh_runtime.experiments.template_runner import applied_params_of

    assert applied_params_of(llm) == {
        "temperature": 0.7, "max_output_tokens": 1200, "parallel_tool_calls": False,
    }

    # 缺省不传递:可选参数 None → 不进入构造(端点默认)
    default_llm = create_llm(api_key="test-key", base_url="http://localhost:9", model="m")
    assert default_llm.max_tokens is None
    assert default_llm.model_kwargs == {}


def test_capability_declares_newly_wired_params():
    from bdlh_runtime.infra.llm import adapter_default_capability, capabilities_of

    cap = adapter_default_capability()
    assert cap.supports_temperature and cap.supports_max_output_tokens and cap.supports_parallel_tool_calls
    assert not cap.supports_top_p and not cap.supports_seed  # 未接线参数仍诚实声明不支持
    payload = cap.as_payload()
    assert payload["supports_max_output_tokens"] is True
    # 未知实现保守 fail-closed:新接线参数同样无法确认
    unknown = capabilities_of(object())
    assert unknown.supports_parallel_tool_calls is False
    assert unknown.supports_max_output_tokens is False


def test_build_llm_for_config_uses_effective_then_requested(monkeypatch):
    """生效值优先;生效缺失时回退请求值(不会静默落到其他口径)。"""
    import bdlh_runtime.infra.llm as llm_module
    from bdlh_runtime.experiments import template_runner as tr
    from bdlh_runtime.experiments.run_config import ModelParams, RunConfig

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9")
    effective = RunConfig(model=ModelParams(temperature_requested=0.7, temperature_effective=0.3))
    fallback = RunConfig(model=ModelParams(temperature_requested=0.5, temperature_effective=None))
    built: list[float] = []

    def spy_create(**kwargs):
        built.append(kwargs.get("temperature"))
        return None  # 只捕获参数,不真正构造

    monkeypatch.setattr(llm_module, "create_llm", spy_create)
    tr.build_llm_for_config(effective)
    tr.build_llm_for_config(fallback)
    assert built == [0.3, 0.5]


@pytest.mark.asyncio
async def test_missing_env_llm_marks_run_invalid(monkeypatch):
    """env 未配置 → 逐运行构建得到 None → 运行诚实记为 INVALID(不冒充成功)。"""
    from bdlh_runtime.experiments.template_runner import run_native_agent
    from bdlh_runtime.experiments.templates import TEMPLATES

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    record = await run_native_agent(
        run_config=TEMPLATES["governance-on-off"].base_config,
        message="测试",
        visible_tools=("web.search",),
        llm=None,
        fixtures=[],
    )
    assert record.validity == "INVALID"
    assert "LLM_UNAVAILABLE" in (record.error or "")
    assert record.applied_model_params == {}


@pytest.mark.asyncio
async def test_template_batch_reports_per_run_progress():
    """on_run_done 每次运行后回调(作业进度):次数=计划运行数,载荷含变体标签。"""
    from bdlh_runtime.experiments import template_runner
    from bdlh_runtime.experiments.templates import plan_template_batch

    plan = plan_template_batch("governance-on-off", repeat_count=1)
    seen: list[dict] = []
    result = await template_runner.run_template_batch(
        plan,
        message="上海天气",
        visible_tools=("weather.get_forecast",),
        llm=FakeChatModel([
            _call("weather.get_forecast", {"location": "上海"}, "c1"),
            AIMessage(content="上海多云。"),
        ] * 2),
        fixtures=[{
            "tool": "weather.get_forecast", "match_mode": "subset",
            "match_arguments": {"location": "上海"}, "status": "success",
            "result": {"forecast": "多云"}, "fixture_id": "fx", "fixture_version": 1,
        }],
        on_run_done=seen.append,
    )
    assert len(seen) == plan.run_count == 2
    assert {row["variant_label"] for row in seen} == {"off", "standard"}
    assert all(row["run_id"] for row in seen)
    assert len(result["runs"]) == 2


def test_owner_batch_list_endpoint_proxies_data_service(owner_client, monkeypatch):
    """GET /api/v1/batches(对接文档 §8 缺口):透传 data 服务分页列表,仅登录可用。"""
    import bdlh_runtime.run_api as run_api

    calls: list[dict] = []

    class StubData:
        def list_batches(self, *, limit=20, cursor=None):
            calls.append({"limit": limit, "cursor": cursor})
            return {
                "batches": [
                    {
                        "id": "b7f3a2c1-0000-0000-0000-000000000001",
                        "name": "模板实验 governance-on-off",
                        "templateId": "governance-on-off",
                        "templateClassification": "formal",
                        "independentVariable": "governance_profile",
                        "repeatCount": 3,
                        "variantCount": 2,
                        "runCount": 6,
                        "status": "COMPLETE",
                    }
                ],
                "nextCursor": None,
            }

    monkeypatch.setattr(run_api, "_data", lambda: StubData())
    response = owner_client.get("/api/v1/batches?limit=5&cursor=abc")
    assert response.status_code == 200
    body = response.json()
    assert body["batches"][0]["templateId"] == "governance-on-off"
    assert body["batches"][0]["runCount"] == 6
    assert calls == [{"limit": 5, "cursor": "abc"}]


def test_owner_batch_list_requires_login():
    from fastapi.testclient import TestClient

    import bdlh_runtime.run_api as run_api

    client = TestClient(run_api.app)
    assert client.get("/api/v1/batches").status_code == 401

