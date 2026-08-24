"""ObservationNormalizer 单元测试，重点验证服务端吞错识别。"""

from __future__ import annotations

import json

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.observations.normalizer import ObservationNormalizer


def _make_obs(raw_text: str, capability: str = "market.get_money_flow") -> Observation:
    """构造一个 SUCCESS 状态、data.raw_text 为给定文本的 Observation。"""
    return Observation(
        observation_id="test-1",
        capability=capability,
        status="SUCCESS",
        data={"raw_text": raw_text, "source_used": None},
        data_quality=DataQuality(completeness=1.0, quality_status="OK"),
        provenance=[
            ProvenanceRecord(source="cn-financial-mcp", tool="get_money_flow", retrieved_at="2026-08-06T00:00:00Z")
        ],
    )


def test_normal_swallowed_error_detected():
    """cn-financial 把 push2 失败包成 {"error":true}，必须识别为 FAILED。"""
    raw = json.dumps({"error": True, "message": "获取资金流向失败: RemoteDisconnected"})
    obs = _make_obs(raw)
    result = ObservationNormalizer().normalize(obs)
    assert result.status == "FAILED"
    assert result.error_code == "SWALLOWED_ERROR"
    assert result.data_quality.quality_status == "INVALID"


def test_normal_response_passes_through():
    """正常 JSON 响应（无 error:true）不误杀。"""
    raw = json.dumps([{"symbol": "600519", "price": 1300.0}])
    obs = _make_obs(raw)
    result = ObservationNormalizer().normalize(obs)
    assert result.status == "SUCCESS"


def test_quote_normalizer_preserves_valuation_identity_and_time():
    obs = _make_obs(
        json.dumps(
            {
                "symbol": "600519",
                "exchange": "SSE",
                "currency": "CNY",
                "price": 1300.0,
                "timestamp": "2026-08-10T10:00:00+08:00",
            }
        ),
        "market.get_realtime_quote",
    )

    result = ObservationNormalizer().normalize(obs)

    assert result.data["exchange"] == "SSE"
    assert result.data["currency"] == "CNY"
    assert result.data["as_of"] == "2026-08-10T10:00:00+08:00"


def test_array_with_error_detected():
    """数组首元素含 error:true 也要识别。"""
    raw = json.dumps([{"error": True, "message": "市场概览失败"}])
    obs = _make_obs(raw, "market.get_market_overview")
    result = ObservationNormalizer().normalize(obs)
    assert result.status == "FAILED"


def test_non_json_text_for_unparsed_capability_passes_through():
    """无专门解析器的能力收到非 JSON 文本 → 保留文本（PARTIAL），不误杀。"""
    # market.get_market_overview 没有注册解析器 → 走文本保留路径
    obs = _make_obs("这不是 JSON，是正常文本", "market.get_market_overview")
    result = ObservationNormalizer().normalize(obs)
    assert result.status == "SUCCESS"
    assert result.data["text"] == "这不是 JSON，是正常文本"


def test_already_failed_not_reprocessed():
    """已经是 FAILED 的 Observation 不再处理。"""
    obs = Observation(
        observation_id="test-2",
        capability="market.get_money_flow",
        status="FAILED",
        data=None,
        data_quality=DataQuality(quality_status="INVALID"),
        provenance=[],
        error_code="MCP_UNAVAILABLE",
    )
    result = ObservationNormalizer().normalize(obs)
    assert result.status == "FAILED"
    assert result.error_code == "MCP_UNAVAILABLE"  # 保留原错误码
