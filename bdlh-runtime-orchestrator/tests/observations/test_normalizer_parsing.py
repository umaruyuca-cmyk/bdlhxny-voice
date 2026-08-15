"""Normalizer 业务数据解析测试（审查文档 §4.1 / §8.2）。

验证：quote、历史K线、财报、新闻的正常响应被解析为统一业务结构。
"""

from __future__ import annotations

import json

from bdlh_runtime.contracts.observation import DataQuality, Observation, ProvenanceRecord
from bdlh_runtime.observations.normalizer import ObservationNormalizer


def _obs(capability: str, raw: str) -> Observation:
    return Observation(
        observation_id="t-1",
        capability=capability,
        status="SUCCESS",
        data={"raw_text": raw, "source_used": None},
        data_quality=DataQuality(completeness=1.0, quality_status="OK"),
        provenance=[ProvenanceRecord(source="cn-financial-mcp", tool=capability, retrieved_at="2026-08-06T00:00:00Z")],
    )


def test_quote_parsed_to_business_object():
    """实时行情 → quote 业务对象（akshare-one 形态）。"""
    raw = json.dumps([{"symbol": "600519", "price": 1302.77, "change": -3.68, "pct_change": -0.28}])
    result = ObservationNormalizer().normalize(_obs("market.get_realtime_quote", raw))
    assert result.status == "SUCCESS"
    assert result.data["symbol"] == "600519"
    assert result.data["price"] == 1302.77
    assert result.data["pct_change"] == -0.28
    # 原始 JSON 不得留在业务 data 里（只留解析后结构）
    assert "raw_text" not in result.data


def test_quote_cn_financial_form_parsed():
    """实时行情（cn-financial K线风格）也兼容。"""
    raw = json.dumps([{"date": "2026-08-05T00:00:00.000", "open": 1328.36, "close": 1306.45, "volume": 4268859.0}])
    result = ObservationNormalizer().normalize(_obs("market.get_realtime_quote", raw))
    assert result.status == "SUCCESS"
    assert result.data["price"] == 1306.45
    assert result.data["trade_date"] == "2026-08-05T00:00:00.000"


def test_historical_prices_parsed_to_bars():
    """历史K线 → 标准化 bar 列表（中文 key 兼容）。"""
    raw = json.dumps([
        {"日期": "2026-07-01", "开盘": 1180.1, "收盘": 1193.01, "最高": 1196.8, "最低": 1166.33, "成交量": 4247400},
        {"日期": "2026-07-02", "开盘": 1193.0, "收盘": 1201.5, "最高": 1205.0, "最低": 1188.0, "成交量": 5000000},
    ])
    result = ObservationNormalizer().normalize(_obs("market.get_historical_prices", raw))
    assert result.status == "SUCCESS"
    bars = result.data
    assert len(bars) == 2
    assert bars[0]["date"] == "2026-07-01"
    assert bars[0]["close"] == 1193.01
    assert bars[1]["high"] == 1205.0


def test_financial_parsed_cn_form():
    """财报（cn-financial 中文 key）解析。"""
    raw = json.dumps([{"报告期": "2026一季报", "货币资金(亿)": 487.87, "营业总收入(亿)": 547.03}])
    result = ObservationNormalizer().normalize(_obs("market.get_financial_statements", raw))
    assert result.status == "SUCCESS"
    assert result.data["report_period"] == "2026一季报"
    assert result.data["unit"] == "亿"


def test_financial_parsed_akshare_form():
    """财报（akshare-one 英文 key）解析。"""
    raw = json.dumps([{"report_date": 1774915200000, "currency": "CNY", "revenue": 54702912385.2}])
    result = ObservationNormalizer().normalize(_obs("market.get_financial_statements", raw))
    assert result.status == "SUCCESS"
    assert result.data["unit"] == "元"


def test_news_parsed_generic_list():
    """新闻 → 结构化列表。"""
    raw = json.dumps([{"keyword": "600519", "title": "茅台新闻", "content": "内容"}])
    result = ObservationNormalizer().normalize(_obs("market.get_news", raw))
    assert result.status == "SUCCESS"
    assert result.data["count"] == 1
    assert result.data["items"][0]["title"] == "茅台新闻"


def test_swallowed_error_detected():
    """服务端吞错（error:true）→ FAILED，不伪装成功。"""
    raw = json.dumps({"error": True, "message": "获取资金流向失败: RemoteDisconnected"})
    result = ObservationNormalizer().normalize(_obs("market.get_money_flow", raw))
    assert result.status == "FAILED"
    assert result.error_code == "SWALLOWED_ERROR"


def test_parse_failure_returns_failed():
    """解析失败 → FAILED，不把垃圾数据当成功。"""
    result = ObservationNormalizer().normalize(_obs("market.get_historical_prices", "not json at all"))
    assert result.status == "FAILED"
    assert result.error_code == "PARSE_ERROR"
