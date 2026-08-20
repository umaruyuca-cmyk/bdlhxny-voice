"""将外部 Adapter 结果转换为统一 Observation，含业务数据解析。

核心职责（审查文档 §4.1）：
MCP 原始返回必须在 Normalizer 中解析为统一的业务结构，而不是只识别
error=true。按 capability 执行字段映射、单位转换和格式校验：
- market.get_realtime_quote → quote 对象（price/change/pct_change/timestamp）
- market.get_historical_prices → K线列表（date/open/high/low/close/volume）
- market.get_financial_statements → 报表对象（中文 key，亿元）
- 其他能力 → 结构化 dict（原始数据 + 来源标记）

原始响应只保留为受控的 raw_reference，不得直接进入 AnalysisInput。
解析失败必须返回 FAILED 或 UNAVAILABLE，不能包装成成功。

服务端吞错识别（审查文档 §4.2 的关联项）：cn-financial 会把数据源失败
包成 {"error": true, "message": "..."} 且 isError=false——本 Normalizer
解析响应体识别，并降级为 FAILED 让路由层触发 fallback。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from bdlh_runtime.contracts.observation import DataQuality, Observation

logger = logging.getLogger("bdlh_runtime.observations.normalizer")


class ObservationNormalizer:
    """标准化入口；禁止将 MCP 原始 JSON 直接传给分析能力。

    流程：
    1. 非 SUCCESS 直接返回；
    2. 服务端吞错检测（error=true）→ FAILED；
    3. 按 capability 解析 raw_text → Observation.data 业务结构；
    4. 解析失败 → FAILED（不伪装成功）。
    """

    def normalize(self, observation: Observation) -> Observation:
        """标准化单个 Observation（不修改原始对象）。"""
        if observation.status not in {"SUCCESS", "PARTIAL"}:
            return observation

        data = observation.data
        if not isinstance(data, dict):
            return observation

        # research.web_search：data 已是结构化 JSON（web_search_adapter 直接放入），
        # 不走 raw_text 解析路径，只做轻量结果清洗。
        if observation.capability == "research.web_search":
            return self._normalize_web_search(observation, data)

        raw_text = data.get("raw_text", "")
        if not raw_text:
            # 无 raw_text 的 dict data 已是结构化业务形态（本地/测试替身/适配器
            # 预解析结果），无需再走 parser——禁止把已结构化数据误判 PARSE_ERROR。
            return observation

        # ── 服务端吞错识别（error=true 藏在正常响应里）──
        swallowed = self._detect_swallowed_error(raw_text)
        if swallowed is not None:
            logger.warning("检测到服务端吞错 (capability=%s): %s", observation.capability, swallowed[:120])
            return self._failure(observation, "SWALLOWED_ERROR", f"服务端将数据源失败包成正常响应: {swallowed[:300]}")

        # ── 按 capability 解析业务数据 ──
        parser = _PARSERS.get(observation.capability)
        if parser is None:
            # 无专门解析器的能力：尝试解析 JSON，保留结构化数据
            return self._generic_parse(observation, raw_text)

        try:
            parsed = parser(raw_text)
            return Observation(
                observation_id=observation.observation_id,
                capability=observation.capability,
                status=observation.status,
                data=parsed,
                data_quality=observation.data_quality,
                provenance=observation.provenance,
                error_code=observation.error_code,
                error_message=observation.error_message,
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("能力 %s 响应解析失败: %s", observation.capability, exc)
            return self._failure(observation, "PARSE_ERROR", f"响应解析失败: {exc}")

    def normalize_many(self, observations: list[Observation]) -> list[Observation]:
        """批量标准化。"""
        return [self.normalize(obs) for obs in observations]

    # ── 内部工具 ──

    def _failure(self, observation: Observation, code: str, message: str) -> Observation:
        """构造失败 Observation（保留 provenance 便于审计）。"""
        return Observation(
            observation_id=observation.observation_id,
            capability=observation.capability,
            status="FAILED",
            data=None,
            data_quality=DataQuality(quality_status="INVALID"),
            provenance=observation.provenance,
            error_code=code,
            error_message=message,
        )

    def _normalize_web_search(self, observation: Observation, data: dict) -> Observation:
        """research.web_search 结果清洗：data 已是 wrapper 结构化响应。

        wrapper 响应：{schemaVersion, requestId, provider, results[], errors[]}。
        这里只做字段裁剪（保留 title/url/snippet/domain/publishedAt/relevanceScore），
        不做内容分析（分析由 Agent/LLM 做）。mock 数据（is_mock=True）原样保留。
        """
        if data.get("is_mock"):
            return observation  # mock 数据不二次清洗，保留 is_mock 标记

        results = data.get("results", [])
        errors = data.get("errors", [])
        cleaned_results = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "domain": r.get("domain"),
                "snippet": r.get("snippet"),
                "published_at": r.get("publishedAt"),
                "relevance_score": r.get("relevanceScore"),
                "source_type": r.get("sourceType"),
            }
            for r in results
            if r.get("url")  # 丢弃无 url 的无效结果
        ]
        status = "PARTIAL" if errors and cleaned_results else observation.status
        quality = DataQuality(
            completeness=min(1.0, len(cleaned_results) / 5.0) if cleaned_results else 0.0,
            quality_status="OK" if cleaned_results else "PARTIAL",
        )
        return Observation(
            observation_id=observation.observation_id,
            capability=observation.capability,
            status=status,
            data={"results": cleaned_results, "errors": errors, "request_id": data.get("requestId"), "provider": data.get("provider")},
            data_quality=quality,
            provenance=observation.provenance,
        )

    def _generic_parse(self, observation: Observation, raw_text: str) -> Observation:
        """无专门解析器时的兜底：尝试 JSON，成功则保留结构。"""
        try:
            parsed: Any = json.loads(raw_text)
            return Observation(
                observation_id=observation.observation_id,
                capability=observation.capability,
                status="SUCCESS",
                data={"data": parsed, "raw_reference": raw_text[:500]},
                data_quality=DataQuality(completeness=1.0, quality_status="OK"),
                provenance=observation.provenance,
            )
        except (json.JSONDecodeError, TypeError):
            # 非 JSON 的纯文本响应（如新闻）：保留文本
            return Observation(
                observation_id=observation.observation_id,
                capability=observation.capability,
                status="SUCCESS",
                data={"text": raw_text[:2000]},
                data_quality=DataQuality(completeness=0.5, quality_status="PARTIAL"),
                provenance=observation.provenance,
            )

    @staticmethod
    def _detect_swallowed_error(raw_text: str) -> str | None:
        """检测响应文本中是否藏有 error:true（服务端吞错）。

        处理两种形态：{"error": true, "message": "..."} 或数组首元素含 error。
        解析失败（非 JSON）返回 None。
        """
        if not raw_text:
            return None
        try:
            parsed: Any = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            return None

        if isinstance(parsed, dict) and parsed.get("error") is True:
            return str(parsed.get("message", parsed.get("msg", "未知错误")))
        if isinstance(parsed, list) and parsed:
            first = parsed[0]
            if isinstance(first, dict) and first.get("error") is True:
                return str(first.get("message", first.get("msg", "未知错误")))
        return None


# ── capability → 业务解析器 映射 ──

_JSON_LOADER: Callable[[str], Any] = json.loads


def _parse_quote(raw: str) -> dict[str, Any]:
    """解析实时行情 → quote 业务对象。

    兼容 cn-financial 和 akshare-one 两种响应形态：
    - cn-financial: [{"date":..., "open":..., "close":..., ...}]（K线风格）
    - akshare-one: [{"symbol":..., "price":..., "change":..., "pct_change":...}]
    """
    parsed = _JSON_LOADER(raw)
    items = parsed if isinstance(parsed, list) else [parsed]
    if not items:
        raise ValueError("quote 响应为空")
    item = items[0] if isinstance(items[0], dict) else {}
    return {
        "symbol": item.get("symbol"),
        "exchange": item.get("exchange"),
        "currency": item.get("currency"),
        "price": item.get("price", item.get("close")),
        "change": item.get("change"),
        "pct_change": item.get("pct_change", item.get("涨跌幅")),
        "volume": item.get("volume", item.get("成交量")),
        "trade_date": item.get("date", item.get("trade_date")),
        "as_of": item.get(
            "as_of",
            item.get("timestamp", item.get("datetime", item.get("date", item.get("trade_date")))),
        ),
    }


def _parse_historical(raw: str) -> list[dict[str, Any]]:
    """解析历史K线 → 标准化 bar 列表。

    兼容中文 key（日期/开盘/收盘/最高/最低/成交量）和英文 key
    （date/open/close/high/low/volume）。统一输出英文 key。
    """
    parsed = _JSON_LOADER(raw)
    if not isinstance(parsed, list):
        raise ValueError("historical prices 响应必须是数组")
    bars: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        bars.append({
            "date": item.get("date", item.get("日期")),
            "open": item.get("open", item.get("开盘")),
            "high": item.get("high", item.get("最高")),
            "low": item.get("low", item.get("最低")),
            "close": item.get("close", item.get("收盘")),
            "volume": item.get("volume", item.get("成交量")),
            "turnover": item.get("turnover", item.get("turnover_rate", item.get("换手率"))),
        })
    if not bars:
        raise ValueError("historical prices 解析后为空")
    return bars


def _parse_financial(raw: str) -> dict[str, Any]:
    """解析财务报表 → 结构化对象。

    cn-financial 返回中文 key（报告期/货币资金(亿) 等），原样保留并加
    报告期标记；akshare-one 返回英文 key（report_date/currency 等），
    统一包一层。
    """
    parsed = _JSON_LOADER(raw)
    if isinstance(parsed, dict) and any(
        name in parsed
        for name in ("balance_sheet", "income_statement", "cash_flow_statement")
    ):
        statements: dict[str, Any] = {}
        for name in ("balance_sheet", "income_statement", "cash_flow_statement"):
            value = parsed.get(name)
            if value is None:
                continue
            if isinstance(value, list):
                statements[name] = value[0] if value and isinstance(value[0], dict) else value
            else:
                statements[name] = value
        if not statements:
            raise ValueError("financial statements 响应为空")
        return {
            "statements": statements,
            "available_statements": sorted(statements),
        }
    if isinstance(parsed, list):
        if not parsed:
            raise ValueError("financial 响应为空")
        item = parsed[0] if isinstance(parsed[0], dict) else {}
    elif isinstance(parsed, dict):
        item = parsed
    else:
        raise ValueError("financial 响应格式不支持")

    # 中文 key 形态（cn-financial）→ 原样
    if any("报告期" in k or "营业" in k for k in item):
        return {"report_period": item.get("报告期"), "items": item, "unit": "亿"}
    # 英文 key 形态（akshare-one）→ 加标记
    return {"report_date": item.get("report_date"), "items": item, "unit": "元"}


def _parse_generic_list(raw: str) -> dict[str, Any]:
    """解析数组型响应（新闻/板块/资金流等）→ 结构化。"""
    parsed = _JSON_LOADER(raw)
    if isinstance(parsed, list):
        return {"items": parsed, "count": len(parsed)}
    if isinstance(parsed, dict):
        return {"data": parsed}
    raise ValueError("响应格式不支持")


def _infer_cn_exchange(symbol: Any) -> str | None:
    """源端未给交易所时，由 6 位 A 股代码推断 SSE/SZSE。"""
    if not isinstance(symbol, str):
        return None
    code = symbol.strip()
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith(("5", "6", "9")):
        return "SSE"
    if code.startswith(("0", "1", "3")):
        return "SZSE"
    return None


def _normalize_instrument_item(item: dict[str, Any]) -> dict[str, Any]:
    symbol = item.get("symbol", item.get("code"))
    if isinstance(symbol, str):
        symbol = symbol.strip()
    exchange = item.get("exchange")
    if not (isinstance(exchange, str) and exchange.strip()):
        exchange = _infer_cn_exchange(symbol)
    elif isinstance(exchange, str):
        exchange = exchange.strip()
    normalized: dict[str, Any] = {
        "symbol": symbol,
        "name": item.get("name"),
        "market": item.get("market", "CN"),
        "exchange": exchange,
        "instrument_type": item.get("instrument_type", "stock"),
    }
    if item.get("canonical_symbol"):
        normalized["canonical_symbol"] = item["canonical_symbol"]
    if item.get("match_type"):
        normalized["match_type"] = item["match_type"]
    if item.get("currency"):
        normalized["currency"] = item["currency"]
    return normalized


def _parse_instrument(raw: str) -> dict[str, Any]:
    """解析标的搜索结果 → 候选列表 + 首条 InstrumentRef 兼容字段。

    cn-financial search_stock 返回 [{"code": "600519", "name": "贵州茅台"}]（常无
    exchange）。必须保留全部候选供 Resolver 判定 AMBIGUOUS，并为 A 股代码推断
    SSE/SZSE；同时保留顶层 symbol/name 供旧 Root Graph assemble_analysis 使用。
    """
    parsed = _JSON_LOADER(raw)
    items: list[Any]
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        nested = None
        for key in ("candidates", "items", "results"):
            value = parsed.get(key)
            if isinstance(value, list) and value:
                nested = value
                break
        items = nested if nested is not None else [parsed]
    else:
        raise ValueError("instrument 响应为空或格式不支持")
    candidates = [
        _normalize_instrument_item(item) for item in items if isinstance(item, dict)
    ]
    if not candidates:
        raise ValueError("instrument 响应为空或格式不支持")
    first = candidates[0]
    return {
        "symbol": first.get("symbol"),
        "name": first.get("name"),
        "market": first.get("market", "CN"),
        "exchange": first.get("exchange"),
        "instrument_type": first.get("instrument_type", "stock"),
        "candidates": candidates,
    }


# 注册表：统一能力 → 解析器
_PARSERS: dict[str, Callable[[str], Any]] = {
    "market.get_realtime_quote": _parse_quote,
    "market.get_historical_prices": _parse_historical,
    "market.get_financial_statements": _parse_financial,
    "market.get_valuation": _parse_generic_list,
    "market.get_industry_context": _parse_generic_list,
    "market.get_money_flow": _parse_generic_list,
    "market.get_news": _parse_generic_list,
    "market.resolve_instrument": _parse_instrument,
}
