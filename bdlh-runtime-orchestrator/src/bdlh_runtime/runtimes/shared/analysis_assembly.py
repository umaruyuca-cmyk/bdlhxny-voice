"""旧 Root Graph 与 Finance Runtime 共用的纯 AnalysisInput 装配核心。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.contracts.analysis import AnalysisInput, InstrumentRef
from bdlh_runtime.contracts.observation import DataQuality, Observation
from bdlh_runtime.tools.coverage import evaluate_coverage


CAPABILITY_TO_ANALYSIS_FIELD: dict[str, str] = {
    "market.resolve_instrument": "instrument",
    "market.get_realtime_quote": "realtime_quote",
    "market.get_historical_prices": "historical_prices",
    "market.get_financial_statements": "financial_data",
    "market.get_valuation": "valuation_data",
    "market.get_industry_context": "industry_context",
    "market.get_money_flow": "money_flow_data",
    "market.get_news": "news_context",
    "research.web_search": "news_context",
    "portfolio.get_current_positions": "portfolio_context",
    "market.get_overseas": "overseas_context",
}


def assemble_analysis_input(
    *,
    analysis_id: str,
    analysis_type: str,
    symbol: str,
    observations: list[Observation],
    requirements: list[dict[str, Any]],
    methodology_version: str = "python-analysis.v1",
) -> AnalysisInput:
    """将标准 Observation 确定性地装配为 AnalysisInput，无 I/O 或框架依赖。"""

    assembled: dict[str, Any] = {}
    known_unavailable: list[str] = []
    provenance: list[Any] = []

    for observation in observations:
        field = CAPABILITY_TO_ANALYSIS_FIELD.get(observation.capability)
        if field is None:
            continue
        provenance.extend(observation.provenance)
        known_unavailable.extend(observation.data_quality.known_unavailable)
        if observation.status not in {"SUCCESS", "PARTIAL"} or observation.data is None:
            known_unavailable.append(observation.capability)
            continue

        if field == "historical_prices":
            assembled[field] = observation.data if isinstance(observation.data, list) else []
        elif field == "news_context":
            if isinstance(observation.data, dict):
                items = observation.data.get("items", observation.data.get("results", []))
            elif isinstance(observation.data, list):
                items = observation.data
            else:
                items = []
            assembled.setdefault(field, []).extend(items if isinstance(items, list) else [])
        else:
            assembled[field] = observation.data

    requirement_dicts = [dict(item) for item in requirements]
    observation_dicts = [item.model_dump() for item in observations]
    coverage = evaluate_coverage(requirement_dicts, observation_dicts)
    known_unavailable.extend(coverage.missing_required)
    known_unavailable.extend(coverage.missing_optional)

    selected = {
        str(item.get("capability"))
        for item in requirement_dicts
        if item.get("capability")
    }
    fulfilled = {
        item.capability
        for item in observations
        if item.status in {"SUCCESS", "PARTIAL"}
        and item.capability in CAPABILITY_TO_ANALYSIS_FIELD
    }
    completeness = len(selected & fulfilled) / len(selected) if selected else 0.0
    if coverage.status == "LIMITED":
        quality_status = "INVALID"
    elif coverage.status == "PARTIAL" or completeness < 1.0:
        quality_status = "PARTIAL"
    else:
        quality_status = "OK"

    instrument_data = assembled.get("instrument") or {"symbol": symbol}
    return AnalysisInput(
        analysis_id=analysis_id,
        analysis_type=analysis_type,
        instrument=InstrumentRef.model_validate(instrument_data),
        realtime_quote=assembled.get("realtime_quote"),
        historical_prices=assembled.get("historical_prices", []),
        financial_data=assembled.get("financial_data"),
        valuation_data=assembled.get("valuation_data"),
        industry_context=assembled.get("industry_context"),
        money_flow_data=assembled.get("money_flow_data"),
        news_context=assembled.get("news_context", []),
        portfolio_context=assembled.get("portfolio_context"),
        overseas_context=assembled.get("overseas_context"),
        data_quality=DataQuality(
            completeness=round(completeness, 2),
            freshness="REALTIME",
            quality_status=quality_status,
            known_unavailable=list(dict.fromkeys(known_unavailable)),
        ),
        provenance=provenance,
        methodology_version=methodology_version,
    )
