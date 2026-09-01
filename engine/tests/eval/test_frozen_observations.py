"""FrozenObservations 查找语义：覆盖键优先、基准回退、未知工具失败桩、负例行(GT-3)。"""

from __future__ import annotations

import pytest

from bdlh_runtime.evaluation.frozen_observations import FrozenObservations
from tests.eval.frozen_fixtures import frozen_payload, negative_payload


@pytest.fixture()
def frozen() -> FrozenObservations:
    return FrozenObservations(frozen_payload())


@pytest.fixture()
def negative() -> FrozenObservations:
    return FrozenObservations(negative_payload())


def test_symbol_override_takes_precedence(frozen: FrozenObservations) -> None:
    assert frozen.get("market.get_realtime_quote", {"symbol": "600519"})["price"] == 1685.00


def test_base_key_fallback_when_no_override(frozen: FrozenObservations) -> None:
    assert frozen.get("market.get_realtime_quote", {"symbol": "300750"})["price"] == 185.50


def test_arguments_optional(frozen: FrozenObservations) -> None:
    assert frozen.get("market.get_realtime_quote")["symbol"] == "300750"


def test_unknown_tool_returns_failure_stub(frozen: FrozenObservations) -> None:
    assert frozen.get("market.no_such_tool", {"symbol": "300750"}) == {
        "status": "FAILED",
        "error": "no frozen observation for: market.no_such_tool",
    }


def test_path_override_resolves_file_tool_calls() -> None:
    """path 覆盖键:文件/代码类工具按 path 参数区分冻结返回(用例自带冻结集)。"""
    table = FrozenObservations(
        {
            "responses": [
                {
                    "call_key": "file.read:db/docs/01-总体设计.md",
                    "response_status": "SUCCESS",
                    "response": {"content": "数据库总体设计……", "lines": 427},
                },
                {
                    "call_key": "file.read:deploy/docker-compose.yml",
                    "response_status": "SUCCESS",
                    "response": {"content": "services: data/engine/web……"},
                },
            ]
        }
    )
    assert table.get("file.read", {"path": "db/docs/01-总体设计.md"})["lines"] == 427
    assert table.get("file.read", {"path": "deploy/docker-compose.yml"})["content"].startswith("services")


def test_unfrozen_path_misses_to_failure_stub() -> None:
    """path 键未冻结且无基准键:失败桩(冻结纪律:脚本外调用不编造返回)。"""
    table = FrozenObservations(
        {"responses": [{"call_key": "file.read:db/docs/a.md", "response_status": "SUCCESS", "response": {"ok": True}}]}
    )
    assert table.get("file.read", {"path": "db/docs/OTHER.md"}) == {
        "status": "FAILED",
        "error": "no frozen observation for: file.read",
    }


def test_symbol_takes_priority_over_path_when_both_present() -> None:
    table = FrozenObservations(
        {
            "responses": [
                {"call_key": "t:sym", "response_status": "SUCCESS", "response": {"k": "symbol"}},
                {"call_key": "t:path", "response_status": "SUCCESS", "response": {"k": "path"}},
            ]
        }
    )
    assert table.get("t", {"symbol": "sym", "path": "path"})["k"] == "symbol"


def test_success_rows_return_response_as_is(negative: FrozenObservations) -> None:
    """正例行(含负例集内的拷贝)与今天完全一致:原样返回 response,无 status 包裹。"""
    result = negative.get("market.get_realtime_quote", {"symbol": "300750"})
    assert result["price"] == 185.50
    assert "status" not in result


# ── GT-3 负例:空结果 / FAILED / TIMEOUT / 部分成功 ──────────────────────


def test_empty_result_is_success_with_empty_content(negative: FrozenObservations) -> None:
    """空结果 = SUCCESS 行 + 空内容:原样返回,模型据空数据继续决策。"""
    result = negative.get("market.get_money_flow", {"symbol": "000000"})
    assert result == {"net_inflow": None, "items": []}
    assert negative.get("market.get_news", {"symbol": "000000"}) == {"items": []}


def test_error_row_returns_status_with_error(negative: FrozenObservations) -> None:
    result = negative.get("market.get_realtime_quote", {"symbol": "999999"})
    assert result == {"status": "ERROR", "error": "symbol not found"}


def test_timeout_row_returns_status_without_wall_clock_delay(negative: FrozenObservations) -> None:
    """TIMEOUT 档不做墙钟延迟(时长只在 simulated_latency_ms 记录)。"""
    result = negative.get("market.get_news", {"symbol": "888888"})
    assert result == {"status": "TIMEOUT", "error": "news source timeout"}


def test_non_symbol_tool_failed_on_base_key(negative: FrozenObservations) -> None:
    """非 symbol 工具负例占基准键(取舍:空/超时档不可表达)。"""
    result = negative.get("research.web_search", {"query": "anything"})
    assert result == {"status": "ERROR", "error": "search backend unavailable"}


def test_override_priority_holds_across_statuses(negative: FrozenObservations) -> None:
    """覆盖键优先语义在负例混排下不变:999999 覆盖 FAILED,基准键仍 SUCCESS。"""
    assert negative.get("market.get_valuation", {"symbol": "999999"})["status"] == "ERROR"
    assert negative.get("market.get_valuation", {"symbol": "300750"})["pe_ttm"] == 28.5
    assert negative.get("market.get_valuation")["pe_ttm"] == 28.5


def test_partial_success_combo_via_override_keys(negative: FrozenObservations) -> None:
    """部分成功:同题两 symbol 一 SUCCESS 一 FAILED(覆盖键组合,无需新机制)。"""
    ok = negative.get("market.get_realtime_quote", {"symbol": "300750"})
    bad = negative.get("market.get_realtime_quote", {"symbol": "999999"})
    assert ok["price"] == 185.50 and "status" not in ok
    assert bad["status"] == "ERROR"


def test_payload_with_rows_but_no_success_is_accepted() -> None:
    """全 FAILED 集合法(极端负例实验):不再要求必须有 SUCCESS 行。"""
    table = FrozenObservations(
        {"responses": [{"call_key": "x", "response_status": "FAILED", "response": {"error": "down"}}]}
    )
    assert table.get("x") == {"status": "FAILED", "error": "down"}


def test_payload_without_any_rows_is_rejected() -> None:
    with pytest.raises(ValueError, match="no responses"):
        FrozenObservations({"responses": []})
