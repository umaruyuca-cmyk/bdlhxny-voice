"""GT-4:工具可见集配置后端——请求字段、三组过滤、不可见口径与 /api/v1/tools。

三组同规则:visible_tools 过滤后,被勾掉的工具被调即计入 invisible_tools
(目录内但本次不可见;目录外编造仍走 hallucinated_tools,三分口径不合并)。
完整模式组 G1 按最终可见集拦截(拒绝+审计码)。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import bdlh_runtime.run_api as run_api
from bdlh_runtime.evaluation.ab_eval import ABCase, _agg_runs, _report_payload, run_ab_eval
from bdlh_runtime.evaluation.frozen_observations import FrozenObservations
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.eval.frozen_fixtures import frozen_payload
from tests.eval.test_run_api import FakeDataClient, _auth
from tests.eval.test_run_telemetry import ScriptedToolModel
from tests.helpers_registry import seeded_snapshot

_GOLD = "market.get_realtime_quote"
_VISIBLE = ["market.get_valuation"]  # 金标工具被勾掉:构造"调不可见工具"行为


@pytest.fixture()
def fake_data(monkeypatch: pytest.MonkeyPatch) -> FakeDataClient:
    data = FakeDataClient()
    monkeypatch.setattr(run_api, "_data", lambda: data)
    return data


@pytest.fixture()
def client(fake_data: FakeDataClient) -> TestClient:
    return TestClient(run_api.app)


def _case() -> ABCase:
    return ABCase(
        id="research-01",
        category="金融研究",
        message="宁德时代现在什么价",
        scene_tag="market",
        expected_tools=(_GOLD,),
        case_version=1,
        variant_id="default",
        snapshot_id="research-01:fixture-v1",
        snapshot_hash="sha256:snap",
    )


async def _run(**kwargs: Any):
    from bdlh_runtime.scenarios import disable_all_scenario_packs, enable_scenario_pack

    enable_scenario_pack("finance")
    try:
        return await run_ab_eval(
            llm=ScriptedToolModel(),  # 恒调 market.get_realtime_quote(金标)
            model="glm-4.7-flash",
            cases=[_case()],
            catalog=catalog_from_snapshot(seeded_snapshot()),
            frozen=FrozenObservations(frozen_payload()),
            retry_delay_s=0,
            inter_run_delay_s=0,
            **kwargs,
        )
    finally:
        disable_all_scenario_packs()


@pytest.mark.asyncio
async def test_baseline_group_filters_cards_and_flags_invisible() -> None:
    """裸调用组:金标工具不在勾选集 → attempted 计入 invisible,记录组可见集收窄。"""
    report = await _run(runs_per_case=1, with_react=False, visible_tools=_VISIBLE)
    judgment = report.cases[0].baseline_runs[0]
    assert judgment.invisible_tools == [_GOLD]
    assert judgment.hallucinated_tools == []  # 目录内不算编造(三分口径)
    assert _agg_runs(report.cases[0].baseline_runs)["invisible"] == 1
    record = report.run_records[0]
    assert _GOLD not in record.visible_tools
    assert "market.get_valuation" in record.visible_tools
    assert report.baseline.invisible_tool_rate == 1.0


@pytest.mark.asyncio
async def test_react_group_flags_invisible_from_attempted() -> None:
    """ReAct 组:attempted_tools 里的不可见调用被捕获(ToolNode 拦截不丢失)。"""
    report = await _run(runs_per_case=1, with_react=True, visible_tools=_VISIBLE)
    assert report.cases[0].react_runs[0].invisible_tools == [_GOLD]
    assert report.react is not None and report.react.invisible_tool_rate == 1.0


@pytest.mark.asyncio
async def test_treatment_group_g1_rejects_unchecked_tool() -> None:
    """完整模式组:最终可见集 = scoped ∩ 勾选;被勾掉的工具被调 → G1 拒绝+审计码。"""
    report = await _run(runs_per_case=1, with_react=False, visible_tools=_VISIBLE)
    judgment = report.cases[0].treatment_runs[0]
    assert judgment.invisible_tools == [_GOLD]
    record = [r for r in report.run_records if r.agent_mode == "full-system"][0]
    assert record.visible_tools == ["market.get_valuation"]
    # G1 拦截留痕:被勾掉的工具在 guardrail 检查明细里被 block
    blocked = [
        row
        for row in (record.guardrail_checks or [])
        if row.tool_name == _GOLD and getattr(row, "decision", None) == "block"
    ]
    assert blocked, "被勾掉的工具被调应产生 G1 拒绝审计"


@pytest.mark.asyncio
async def test_explicit_empty_set_binds_no_tools() -> None:
    """能力缺口实验:visible_tools=[] → 裸调用组零工具可见,任何调用都不可见。"""
    report = await _run(runs_per_case=1, with_react=False, visible_tools=[])
    judgment = report.cases[0].baseline_runs[0]
    assert judgment.invisible_tools == [_GOLD]
    record = report.run_records[0]
    assert record.visible_tools == []
    assert report.visible_tools == []
    assert _report_payload(report)["visible_tools"] == []


@pytest.mark.asyncio
async def test_no_override_keeps_current_behavior() -> None:
    """反例:visible_tools=None → 三组行为不变,不可见率 0。"""
    report = await _run(runs_per_case=1, with_react=False)
    judgment = report.cases[0].baseline_runs[0]
    assert judgment.invisible_tools == []
    assert report.baseline.invisible_tool_rate == 0.0
    assert report.visible_tools is None
    assert _report_payload(report)["visible_tools"] is None


@pytest.mark.asyncio
async def test_report_payload_carries_visible_tools() -> None:
    report = await _run(runs_per_case=1, with_react=False, visible_tools=list(_VISIBLE))
    payload = _report_payload(report)
    assert payload["visible_tools"] == sorted(_VISIBLE)
    assert payload["groups"]["baseline"]["invisible_tool_rate"] == 1.0


def test_unknown_tool_name_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/eval-batches",
        json={"case_ids": ["research-01"], "runs": 1, "visible_tools": ["nope.tool"]},
        headers=_auth(),
    )
    assert response.status_code == 400
    assert "未知工具名" in response.json()["detail"]
    assert "nope.tool" in response.json()["detail"]


def test_known_tool_name_and_search_tools_accepted(
    client: TestClient,
    fake_data: FakeDataClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """目录内名 + search_tools(引擎侧伴侣元工具)均通过校验。"""
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)

    def fake_execute(
        _request: Any, _catalog: Any, job: Any = None, llm_config=None
    ) -> tuple[dict[str, Any], list[Any]]:
        return {"run_records": []}, []

    # 替换执行器并等待任务完成:不留下仍在持有批次槽位的后台线程
    # (否则紧随其后的批次测试会因 MAX_CONCURRENT_BATCHES=1 撞 429)
    monkeypatch.setattr(run_api, "_execute_eval", fake_execute)
    response = client.post(
        "/api/v1/eval-batches",
        json={"case_ids": ["research-01"], "runs": 1, "visible_tools": ["market.get_valuation", "search_tools"]},
        headers=_auth(),
    )
    assert response.status_code == 200
    from tests.eval.test_run_api import _poll

    job = _poll(client, response.json()["job_id"])
    assert job["status"] == "done", job.get("error")


def _capture_conditions(
    client: TestClient,
    fake_data: FakeDataClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    body: dict[str, Any],
) -> dict[str, Any]:
    """发起一批次并捕获 create_batch 的 fixed_conditions(执行用假件替代)。"""
    monkeypatch.setattr(run_api, "ARTIFACTS_DIR", tmp_path)
    from tests.eval.test_run_api import _poll, _sample_recorder

    recorder = _sample_recorder("baseline-tool-calling")

    def fake_execute(
        _request: Any, _catalog: Any, job: Any = None, llm_config=None
    ) -> tuple[dict[str, Any], list[Any]]:
        return {"run_records": [{"run_key": recorder.record.run_key, "run_id": None}]}, [recorder.record]

    monkeypatch.setattr(run_api, "_execute_eval", fake_execute)
    captured: dict[str, Any] = {}

    def create_batch(*, name: str, fixed_conditions: dict[str, Any]) -> str:
        captured.update(fixed_conditions)
        return "batch-1"

    fake_data.create_batch = create_batch  # type: ignore[method-assign]
    response = client.post("/api/v1/eval-batches", json=body, headers=_auth())
    assert response.status_code == 200
    job = _poll(client, response.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    return captured


def test_empty_visible_list_is_explicit_empty_set(
    client: TestClient,
    fake_data: FakeDataClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """[] 与 null 严格区分(GT-5 取舍):空集落库为 [],不做默认归一。"""
    captured = _capture_conditions(
        client,
        fake_data,
        monkeypatch,
        tmp_path,
        {"case_ids": ["research-01"], "runs": 1, "include_react": False, "visible_tools": []},
    )
    assert captured["visibleTools"] == []
    assert captured["fixtureSetId"] == "ab-eval"


def test_visible_tools_persisted_in_fixed_conditions(
    client: TestClient,
    fake_data: FakeDataClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """指定可见集:fixed_conditions 落 visibleTools(配置随批次记录,指标可归因)。"""
    captured = _capture_conditions(
        client,
        fake_data,
        monkeypatch,
        tmp_path,
        {"case_ids": ["research-01"], "runs": 1, "include_react": False, "visible_tools": _VISIBLE},
    )
    assert captured["visibleTools"] == _VISIBLE


def test_tools_endpoint_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/tools").status_code == 401


def test_tools_endpoint_proxies_catalog(client: TestClient) -> None:
    response = client.get("/api/v1/tools", headers=_auth())
    assert response.status_code == 200
    tools = response.json()
    names = [tool["name"] for tool in tools]
    assert "market.get_realtime_quote" in names
    for tool in tools:
        assert set(tool) == {"name", "description", "domain", "enabled", "side_effect", "risk_level"}
        assert tool["enabled"] is True
        assert tool["side_effect"] == "none"
        assert tool["risk_level"] == "low"
