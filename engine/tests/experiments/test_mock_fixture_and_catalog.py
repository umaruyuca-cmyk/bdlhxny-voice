"""Prompt 08: Mock 匹配、工具目录、fixture 哈希与静态校验。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bdlh_runtime.experiments.case_validator import (
    validate_all,
    validate_all_comparison_cases,
    validate_public_projection,
    validate_session_golds,
)
from bdlh_runtime.experiments.comparison_cases_data import (
    COMPARISON_CASES,
    FIXTURE_SET_VERSION,
    PLACEHOLDER_EXCERPT,
    all_mock_fixtures,
    fixture_set_source_hash,
)
from bdlh_runtime.experiments.fixture_executor import FrozenFixtureExecutor
from bdlh_runtime.experiments.fixture_hash import catalog_schema_hash, fixture_content_hash, normalize_fixture
from bdlh_runtime.experiments.public_case_repository import DataClientCaseRepository
from bdlh_runtime.experiments.tool_catalog_snapshot import (
    ComparisonToolCatalogError,
    build_comparison_catalog,
    tool_manifests,
)


def test_correct_args_hit_fixture_wrong_args_not_in_fixture():
    fixtures = [
        {
            "tool": "order.get_status",
            "match_mode": "subset",
            "match_arguments": {"order_id": "ORD-2049"},
            "status": "success",
            "result": {"status": "已发货"},
            "fixture_id": "fx-1",
            "fixture_version": 2,
        }
    ]
    executor = FrozenFixtureExecutor(fixtures, fixture_version=2)

    async def _run():
        ok = await executor("order.get_status", {"order_id": "ORD-2049"})
        bad = await executor("order.get_status", {"order_id": "WRONG"})
        return ok, bad

    ok, bad = asyncio.run(_run())
    assert ok["status"] == "success"
    assert ok["simulated"] is True
    assert ok["fixture_id"] == "fx-1"
    assert bad["error_code"] == "NOT_IN_FIXTURE"
    assert bad["status"] == "error"


def test_path_product_url_misses_return_not_in_fixture():
    fixtures = [
        {
            "tool": "file.read",
            "match_arguments": {"path": "docs/a.md"},
            "status": "success",
            "result": {"content_excerpt": "A"},
            "fixture_id": "f1",
        },
        {
            "tool": "product.get_price",
            "match_arguments": {"product_id": "SKU-9012"},
            "status": "success",
            "result": {"price": 899},
            "fixture_id": "f2",
        },
        {
            "tool": "web.extract",
            "match_arguments": {"url": "https://ir.example/2026q2"},
            "status": "success",
            "result": {"revenue_growth": "41.7"},
            "fixture_id": "f3",
        },
    ]
    executor = FrozenFixtureExecutor(fixtures)

    async def _run():
        return (
            await executor("file.read", {"path": "docs/b.md"}),
            await executor("product.get_price", {"product_id": "SKU-0000"}),
            await executor("web.extract", {"url": "https://evil.example"}),
        )

    for payload in asyncio.run(_run()):
        assert payload["error_code"] == "NOT_IN_FIXTURE"


def test_required_params_reject_empty_match_in_validator():
    case = {
        "case_id": "tmp-empty-match",
        "allowed_tools": ["order.get_status"],
        "default_visible_tools": ["order.get_status"],
        "call_relation": {"required_calls": [{"tool": "order.get_status", "arguments": {"order_id": "X"}}]},
        "mock_fixtures": [
            {
                "fixture_id": "bad",
                "tool": "order.get_status",
                "match_mode": "subset",
                "match_arguments": {},
                "status": "success",
                "result": {"status": "ok"},
            }
        ],
    }
    from bdlh_runtime.experiments.case_validator import validate_comparison_case

    report = validate_comparison_case(case)
    assert any("空匹配" in issue.reason for issue in report.issues)


@pytest.mark.parametrize(
    "status",
    ["success", "empty", "timeout", "denied", "stale", "conflict", "error"],
)
def test_fixture_statuses_recorded(status: str):
    fixtures = [
        {
            "tool": "web.search",
            "match_arguments": {"query": "q"},
            "status": status,
            "result": {"ok": True},
            "fixture_id": f"st-{status}",
        }
    ]
    executor = FrozenFixtureExecutor(fixtures)

    async def _run():
        return await executor("web.search", {"query": "q"})

    payload = asyncio.run(_run())
    assert payload["status"] == status
    assert executor.call_records[0]["status"] == status


def test_same_tools_share_same_schema_and_hash():
    tools = ("order.get_status", "crm.search_customer", "support.search_tickets")
    catalog_a, cards_a = build_comparison_catalog(tools)
    catalog_b, cards_b = build_comparison_catalog(tools)
    catalog_c, cards_c = build_comparison_catalog(list(tools))
    ha = catalog_schema_hash(tool_manifests(cards_a))
    hb = catalog_schema_hash(tool_manifests(cards_b))
    hc = catalog_schema_hash(tool_manifests(cards_c))
    assert ha == hb == hc
    assert [c.name for c in cards_a] == list(tools)
    assert cards_a[0].parameters.get("properties")
    assert "order_id" in cards_a[0].parameters["properties"]
    assert "冻结 Mock 工具" not in cards_a[0].description
    assert len(catalog_a) == 3 and len(catalog_b) == 3 and len(catalog_c) == 3


def test_missing_tool_fails_before_empty_schema():
    with pytest.raises(ComparisonToolCatalogError):
        build_comparison_catalog(("not.a.real.tool",))


def test_fixture_hash_stable_under_key_reorder_and_sensitive_to_content():
    fixtures = all_mock_fixtures()
    base = fixture_content_hash(fixtures, fixture_version=FIXTURE_SET_VERSION)
    assert base == fixture_set_source_hash()
    reordered = []
    for row in fixtures:
        clone = {
            "result": row["result"],
            "status": row["status"],
            "tool": row["tool"],
            "match_mode": row.get("match_mode") or "subset",
            "match_arguments": dict(reversed(list((row.get("match_arguments") or {}).items()))),
            "fixture_id": row["fixture_id"],
            "fixture_version": FIXTURE_SET_VERSION,
        }
        reordered.append(clone)
    assert fixture_content_hash(reordered, fixture_version=FIXTURE_SET_VERSION) == base
    mutated = [dict(fixtures[0]), *fixtures[1:]]
    mutated[0] = {**mutated[0], "result": {**(mutated[0].get("result") or {}), "x": 1}}
    assert fixture_content_hash(mutated, fixture_version=FIXTURE_SET_VERSION) != base
    normalized = normalize_fixture(fixtures[0], fixture_version=FIXTURE_SET_VERSION)
    assert "captured_at" not in normalized


def test_all_twenty_cases_pass_static_validation():
    report = validate_all_comparison_cases()
    assert report.ok, [issue.as_dict() for issue in report.issues]
    assert len(COMPARISON_CASES) == 20


def test_session_golds_have_real_excerpts():
    report = validate_session_golds()
    assert report.ok, [issue.as_dict() for issue in report.issues]
    root = Path(__file__).resolve().parents[2] / "var" / "cases"
    for name in (
        "ctx-session-product-evolution-01",
        "ctx-session-context-engine-debug-01",
        "ctx-session-database-deploy-01",
    ):
        gold = json.loads((root / name / "gold" / f"{name}.gold.json").read_text(encoding="utf-8"))
        for fixture in gold["runtime_mock_fixtures"]:
            excerpt = fixture["result"]["content_excerpt"]
            assert PLACEHOLDER_EXCERPT not in excerpt
            assert fixture["result"]["simulated"] is True
            assert fixture["result"]["content_hash"].startswith("sha256:")


def test_public_projection_hides_internal_fields():
    class FakeRepo(DataClientCaseRepository):
        def list_public_cases(self):  # type: ignore[override]
            from bdlh_runtime.experiments.comparison import ComparisonCase
            from bdlh_runtime.experiments.judge import CallRelationSpec

            return [
                ComparisonCase(
                    case_id="cmp-basic-single-01",
                    case_version=1,
                    title="t",
                    message="m",
                    scene="general",
                    allowed_tools=("order.get_status",),
                    default_visible_tools=("order.get_status",),
                    fixture_set_id="cmp-fixtures-v2",
                    call_relation=CallRelationSpec(),
                    conditions={"mock_fixtures": [{"tool": "order.get_status"}]},
                )
            ]

    rows = FakeRepo().public_projection()
    report = validate_public_projection(rows)
    assert report.ok
    assert "mock_fixtures" not in rows[0]
    assert "call_relation" not in rows[0]


def test_validate_all_includes_sessions():
    report = validate_all()
    assert report.ok, [issue.as_dict() for issue in report.issues]


def test_production_path_does_not_mock_final_answer(monkeypatch):
    """生产执行器没有固定最终答案路径;本测试只检查模块级不存在答案表。"""
    import bdlh_runtime.experiments.fixture_executor as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "MOCK_FINAL_ANSWER" not in source
    assert "fixed_answer" not in source
