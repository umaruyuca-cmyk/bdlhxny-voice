"""M2 客观股票研究结果的确定性 Builder。

本模块无 I/O、无 LangGraph/MCP/FastAPI 依赖，也不调用 LLM。它只把已经规划并
标准化的 Observation 与过渡期 AnalysisResult 投影为 StockResearchResult。
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Iterable, Literal

from stockwise_analysis.contracts.analysis import AnalysisResult
from stockwise_analysis.contracts.data_requirements import DataRequirement
from stockwise_analysis.contracts.observation import Observation, ProvenanceRecord
from stockwise_analysis.domains.contracts import ConfidenceAssessment
from stockwise_analysis.tools.coverage import evaluate_coverage

from .contracts import (
    EvidenceConflict,
    EvidenceFact,
    FinancialDomainRequest,
    Fundamentals,
    Finding,
    IndustryContext,
    MarketSnapshot,
    MoneyFlow,
    NewsEvent,
    ResearchRisk,
    StockResearchResult,
    Technicals,
    Valuation,
)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_HTML_TAG = re.compile(r"<[^>]+>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_QUOTE = "market.get_realtime_quote"
_HISTORY = "market.get_historical_prices"
_FINANCIALS = "market.get_financial_statements"
_VALUATION = "market.get_valuation"
_INDUSTRY = "market.get_industry_context"
_MONEY_FLOW = "market.get_money_flow"
_NEWS = "market.get_news"
_WEB = "research.web_search"

Quality = Literal["HIGH", "MEDIUM", "LOW", "INVALID"]
Coverage = Literal["COMPLETE", "PARTIAL", "LIMITED"]


class StockResearchResultBuilder:
    """以可复现策略构建股票研究结果，禁止隐式补查或自由生成字段。"""

    def build(
        self,
        *,
        request: FinancialDomainRequest,
        requirements: list[DataRequirement],
        observations: list[Observation],
        analysis_result: AnalysisResult,
        runtime_limitations: Iterable[str] = (),
    ) -> StockResearchResult:
        planned = {item.capability for item in requirements}
        selected = sorted(
            (item for item in observations if item.capability in planned),
            key=lambda item: (item.capability, item.observation_id),
        )
        usable = [
            item
            for item in selected
            if item.status in {"SUCCESS", "PARTIAL"} and item.data is not None
        ]

        evidence = [self._evidence(item) for item in usable]
        evidence_by_observation = {
            item.observation_id: fact.fact_id
            for item, fact in zip(usable, evidence, strict=True)
        }
        conflicts = self._conflicts(usable, evidence_by_observation)
        conflicting_observations = {
            ref.removeprefix("evidence:")
            for conflict in conflicts
            for ref in conflict.evidence_refs
        }

        limitations = list(runtime_limitations) + list(analysis_result.limitations)
        for requirement in requirements:
            candidates = [item for item in usable if item.capability == requirement.capability]
            if not candidates:
                limitations.append(
                    f"Planned capability unavailable: {requirement.capability}"
                )
        for item in usable:
            if not item.provenance:
                limitations.append(
                    f"Evidence provenance missing: {item.capability}/{item.observation_id}"
                )

        base_coverage = evaluate_coverage(
            [item.model_dump() for item in requirements],
            [item.model_dump() for item in selected],
        ).status
        coverage = self._research_coverage(
            base_coverage=base_coverage,
            analysis_status=analysis_result.status,
            observations=selected,
            evidence=evidence,
            has_conflicts=bool(conflicts),
        )
        confidence = self._confidence(
            coverage=coverage,
            analysis_status=analysis_result.status,
            conflicts=conflicts,
            evidence=evidence,
        )
        if conflicts:
            limitations.append("Conflicting evidence requires source reconciliation")
        if any(self._data_mode(item) != "LIVE" for item in selected):
            limitations.append("Non-live data cannot support complete live research")

        by_capability: dict[str, list[Observation]] = defaultdict(list)
        for item in usable:
            by_capability[item.capability].append(item)

        market_snapshot = None
        if _QUOTE in planned and by_capability[_QUOTE]:
            quote = by_capability[_QUOTE][0]
            data = self._first_mapping(quote.data)
            market_snapshot = MarketSnapshot(
                symbol=str(data.get("symbol") or request.instruments[0].symbol),
                name=request.instruments[0].name,
                price=self._number(data, "price", "close", "最新价"),
                currency=str(data.get("currency") or "CNY"),
                trade_date=self._datetime(
                    data.get("trade_date", data.get("date", data.get("as_of")))
                ),
                source_time=self._source_time(quote),
                quality=self._section_quality(quote, conflicting_observations),
            )

        fundamentals = None
        if _FINANCIALS in planned and by_capability[_FINANCIALS]:
            item = by_capability[_FINANCIALS][0]
            fundamentals = Fundamentals(
                revenue=self._number_deep(item.data, "revenue", "营业收入", "营收"),
                net_profit=self._number_deep(item.data, "net_profit", "净利润"),
                revenue_yoy=self._number_deep(
                    item.data, "revenue_yoy", "revenue_growth", "营收同比"
                ),
                net_profit_yoy=self._number_deep(
                    item.data, "net_profit_yoy", "profit_growth", "净利润同比"
                ),
                roe=self._number_deep(item.data, "roe", "ROE", "净资产收益率"),
                debt_ratio=self._number_deep(
                    item.data, "debt_ratio", "asset_liability_ratio", "资产负债率"
                ),
                quality=self._section_quality(item, conflicting_observations),
            )

        valuation = None
        if _VALUATION in planned and by_capability[_VALUATION]:
            item = by_capability[_VALUATION][0]
            valuation = Valuation(
                pe=self._number_deep(item.data, "pe", "pe_ttm", "市盈率"),
                pb=self._number_deep(item.data, "pb", "市净率"),
                ps=self._number_deep(item.data, "ps", "市销率"),
                method=self._text_deep(item.data, "method", "valuation_method"),
                quality=self._section_quality(item, conflicting_observations),
            )

        technicals = None
        if _HISTORY in planned and by_capability[_HISTORY]:
            item = by_capability[_HISTORY][0]
            technicals = Technicals(
                trend=self._trend(analysis_result.signals),
                indicators=self._json_value(analysis_result.calculated_indicators),
                quality=self._section_quality(item, conflicting_observations),
                limitations=list(analysis_result.limitations),
            )

        money_flow = None
        if _MONEY_FLOW in planned and by_capability[_MONEY_FLOW]:
            item = by_capability[_MONEY_FLOW][0]
            money_flow = MoneyFlow(
                net_inflow=self._number_deep(
                    item.data, "net_inflow", "main_net_inflow", "主力净流入"
                ),
                quality=self._section_quality(item, conflicting_observations),
            )

        industry_context = None
        if _INDUSTRY in planned and by_capability[_INDUSTRY]:
            item = by_capability[_INDUSTRY][0]
            industry_context = IndustryContext(
                industry=self._text_deep(item.data, "industry", "industry_name", "行业"),
                peers=self._string_list_deep(item.data, "peers", "peer_symbols"),
                quality=self._section_quality(item, conflicting_observations),
            )

        events: list[NewsEvent] = []
        for capability in (_NEWS, _WEB):
            if capability not in planned:
                continue
            for item in by_capability[capability]:
                events.extend(self._events(item))

        evidence_ids = [item.fact_id for item in evidence]
        calculation_ids = [
            f"calculation:{analysis_result.methodology_version}:{name}"
            for name in sorted(analysis_result.calculated_indicators)
            if name != "engine"
        ]
        findings = self._findings(
            analysis_result,
            evidence_ids=evidence_ids,
            calculation_ids=calculation_ids,
            maximum_confidence=confidence.level,
        )
        risks = self._risks(analysis_result, evidence_ids)

        return StockResearchResult(
            instrument=request.instruments[0],
            market_snapshot=market_snapshot,
            fundamentals=fundamentals,
            valuation=valuation,
            technicals=technicals,
            money_flow=money_flow,
            industry_context=industry_context,
            events=events,
            scenarios=[],
            risks=risks,
            evidence=evidence,
            findings=findings,
            conflicts=conflicts,
            coverage=coverage,
            confidence=confidence,
            limitations=self._unique(limitations),
        )

    def _evidence(self, observation: Observation) -> EvidenceFact:
        provenance = observation.provenance[0] if observation.provenance else None
        retrieved_at = self._datetime(provenance.retrieved_at if provenance else None)
        source = provenance.source if provenance else "UNATTRIBUTED"
        return EvidenceFact(
            fact_id=f"evidence:{observation.observation_id}",
            statement=f"Observed {observation.capability}",
            value=self._evidence_value(observation),
            # 只暴露受控 Observation 引用，不把 raw_reference 内容复制到结果。
            source_refs=[observation.observation_id],
            directness="DIRECT",
            source=source,
            source_time=self._source_time(observation),
            retrieved_at=retrieved_at or _EPOCH,
            quality=self._observation_quality(observation),
        )

    def _conflicts(
        self,
        observations: list[Observation],
        evidence_by_observation: dict[str, str],
    ) -> list[EvidenceConflict]:
        grouped: dict[str, list[Observation]] = defaultdict(list)
        for item in observations:
            grouped[item.capability].append(item)

        conflicts: list[EvidenceConflict] = []
        for capability in sorted(grouped):
            items = sorted(grouped[capability], key=lambda item: item.observation_id)
            if len(items) < 2:
                continue
            baseline = items[0]
            left_values = self._semantic_values(baseline)
            for candidate in items[1:]:
                right_values = self._semantic_values(candidate)
                differing = sorted(
                    key
                    for key in left_values.keys() & right_values.keys()
                    if self._canonical(left_values[key]) != self._canonical(right_values[key])
                )
                if not differing:
                    continue
                left_ref = evidence_by_observation[baseline.observation_id]
                right_ref = evidence_by_observation[candidate.observation_id]
                conflicts.append(
                    EvidenceConflict(
                        conflict_id=(
                            f"conflict:{capability}:{baseline.observation_id}:"
                            f"{candidate.observation_id}"
                        ),
                        description=(
                            f"Conflicting {capability} semantic fields: "
                            + ", ".join(differing)
                        ),
                        left_refs=[left_ref],
                        right_refs=[right_ref],
                        materiality=(
                            "HIGH"
                            if capability in {_QUOTE, _FINANCIALS, _VALUATION, _MONEY_FLOW}
                            else "MEDIUM"
                        ),
                        evidence_refs=[left_ref, right_ref],
                    )
                )
        return conflicts

    def _semantic_values(self, observation: Observation) -> dict[str, Any]:
        aliases: dict[str, tuple[tuple[str, ...], ...]] = {
            _QUOTE: (("price", "close", "最新价"),),
            _FINANCIALS: (
                ("revenue", "营业收入", "营收"),
                ("net_profit", "净利润"),
                ("revenue_yoy", "revenue_growth", "营收同比"),
                ("net_profit_yoy", "profit_growth", "净利润同比"),
                ("roe", "ROE", "净资产收益率"),
                ("debt_ratio", "asset_liability_ratio", "资产负债率"),
            ),
            _VALUATION: (
                ("pe", "pe_ttm", "市盈率"),
                ("pb", "市净率"),
                ("ps", "市销率"),
            ),
            _MONEY_FLOW: (("net_inflow", "main_net_inflow", "主力净流入"),),
            _INDUSTRY: (("industry", "industry_name", "行业"),),
        }
        values: dict[str, Any] = {}
        for names in aliases.get(observation.capability, ()):
            if observation.capability == _INDUSTRY:
                value = self._text_deep(observation.data, *names)
            else:
                value = self._number_deep(observation.data, *names)
            if value is not None:
                values[names[0]] = value
        return values

    def _research_coverage(
        self,
        *,
        base_coverage: str,
        analysis_status: str,
        observations: list[Observation],
        evidence: list[EvidenceFact],
        has_conflicts: bool,
    ) -> Coverage:
        if (
            analysis_status in {"FAILED", "LIMITED"}
            or base_coverage == "LIMITED"
            or not evidence
        ):
            return "LIMITED"
        modes = {self._data_mode(item) for item in observations}
        if "UNAVAILABLE" in modes or "MOCK" in modes:
            return "LIMITED"
        if (
            analysis_status == "PARTIAL"
            or base_coverage == "PARTIAL"
            or has_conflicts
            or "TEST_FIXTURE" in modes
            or any(item.quality in {"LOW", "INVALID"} for item in evidence)
        ):
            return "PARTIAL"
        return "COMPLETE"

    @staticmethod
    def _confidence(
        *,
        coverage: Coverage,
        analysis_status: str,
        conflicts: list[EvidenceConflict],
        evidence: list[EvidenceFact],
    ) -> ConfidenceAssessment:
        if analysis_status in {"FAILED", "LIMITED"} or coverage == "LIMITED":
            level = "LOW"
        elif conflicts or any(item.quality in {"LOW", "INVALID"} for item in evidence):
            level = "LOW"
        elif coverage == "PARTIAL" or analysis_status == "PARTIAL":
            level = "MEDIUM"
        else:
            level = "HIGH"
        quality_order = {"INVALID": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
        worst_quality = min(
            (item.quality for item in evidence),
            default="INVALID",
            key=lambda item: quality_order[item],
        )
        return ConfidenceAssessment(
            level=level,
            coverage_status=coverage,
            reasons=[
                f"coverage={coverage}",
                f"analysis={analysis_status}",
                f"conflicts={len(conflicts)}",
                f"evidence_quality={worst_quality}",
            ],
        )

    @staticmethod
    def _findings(
        analysis_result: AnalysisResult,
        *,
        evidence_ids: list[str],
        calculation_ids: list[str],
        maximum_confidence: str,
    ) -> list[Finding]:
        if analysis_result.status in {"FAILED", "LIMITED"}:
            return []
        confidence_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        findings: list[Finding] = []
        for index, conclusion in enumerate(analysis_result.conclusions):
            statement = str(conclusion.get("text", "")).strip()
            if not statement or not (evidence_ids or calculation_ids):
                continue
            requested = str(conclusion.get("confidence", "LOW")).upper()
            if requested not in confidence_order:
                requested = "LOW"
            confidence = min(
                (requested, maximum_confidence),
                key=lambda item: confidence_order[item],
            )
            findings.append(
                Finding(
                    finding_id=f"finding:{analysis_result.analysis_id}:{index}",
                    statement=statement,
                    evidence_ids=list(evidence_ids),
                    calculation_ids=list(calculation_ids),
                    confidence=confidence,
                    invalidation_conditions=[
                        "Newer observations or corrected calculation inputs"
                    ],
                )
            )
        return findings

    @staticmethod
    def _risks(
        analysis_result: AnalysisResult,
        evidence_ids: list[str],
    ) -> list[ResearchRisk]:
        severity_map = {
            "low": "LOW",
            "medium": "MEDIUM",
            "high": "HIGH",
            "critical": "CRITICAL",
        }
        risks: list[ResearchRisk] = []
        for index, item in enumerate(analysis_result.risk_flags):
            name = str(item.get("name") or f"risk-{index}")
            detail = str(item.get("detail") or name)
            severity = severity_map.get(str(item.get("severity", "medium")).lower(), "MEDIUM")
            risks.append(
                ResearchRisk(
                    risk_id=f"risk:{analysis_result.analysis_id}:{index}:{name}",
                    description=detail,
                    severity=severity,
                    evidence_ids=list(evidence_ids),
                    invalidation_conditions=[
                        "Newer observations or corrected calculation inputs"
                    ],
                )
            )
        return risks

    def _events(self, observation: Observation) -> list[NewsEvent]:
        data = observation.data
        if isinstance(data, dict):
            raw_items = data.get("items", data.get("results", data.get("data", [])))
        else:
            raw_items = data
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        if not isinstance(raw_items, list):
            return []
        provenance_source = (
            observation.provenance[0].source
            if observation.provenance
            else observation.capability
        )
        events: list[NewsEvent] = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                continue
            headline = self._clean_text(item.get("headline", item.get("title")))
            if not headline:
                continue
            sentiment = str(item.get("sentiment", "UNKNOWN")).upper()
            if sentiment not in {"POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"}:
                sentiment = "UNKNOWN"
            events.append(
                NewsEvent(
                    event_id=f"event:{observation.observation_id}:{index}",
                    headline=headline,
                    source=str(item.get("source") or item.get("domain") or provenance_source),
                    published_at=self._datetime(
                        item.get("published_at", item.get("publishedAt"))
                    ),
                    sentiment=sentiment,
                )
            )
        return events

    def _evidence_value(self, observation: Observation) -> Any:
        """新闻/网页证据只保留受控元数据，避免把外部正文或指令带入结果。"""
        if observation.capability not in {_NEWS, _WEB}:
            return self._json_value(observation.data)
        data = observation.data
        if isinstance(data, dict):
            raw_items = data.get("items", data.get("results", data.get("data", [])))
        else:
            raw_items = data
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        if not isinstance(raw_items, list):
            return []
        sanitized: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            headline = self._clean_text(item.get("headline", item.get("title")))
            if not headline:
                continue
            sanitized.append(
                {
                    "headline": headline,
                    "source": item.get("source", item.get("domain")),
                    "published_at": item.get("published_at", item.get("publishedAt")),
                    "url": item.get("url"),
                }
            )
        return self._json_value(sanitized)

    @staticmethod
    def _trend(signals: list[dict[str, Any]]) -> str:
        directions = {str(item.get("direction", "")).lower() for item in signals}
        bullish = bool(directions & {"bullish", "reversal_up"})
        bearish = bool(directions & {"bearish", "reversal_down"})
        if bullish and not bearish:
            return "UP"
        if bearish and not bullish:
            return "DOWN"
        if directions:
            return "SIDEWAYS"
        return "UNKNOWN"

    def _section_quality(
        self,
        observation: Observation,
        conflicting_observations: set[str],
    ) -> Quality:
        if observation.observation_id in conflicting_observations:
            return "LOW"
        return self._observation_quality(observation)

    def _observation_quality(self, observation: Observation) -> Quality:
        if observation.status in {"FAILED", "UNAVAILABLE"} or observation.data is None:
            return "INVALID"
        mode = self._data_mode(observation)
        if mode in {"MOCK", "UNAVAILABLE"}:
            return "INVALID"
        if not observation.provenance:
            return "LOW"
        quality = observation.data_quality.quality_status
        if observation.status == "PARTIAL" or quality in {"PARTIAL", "STALE"}:
            return "MEDIUM"
        if quality == "INVALID":
            return "INVALID"
        if mode == "TEST_FIXTURE":
            return "LOW"
        if quality == "OK":
            return "HIGH"
        return "MEDIUM"

    @staticmethod
    def _data_mode(observation: Observation) -> str:
        if observation.status in {"FAILED", "UNAVAILABLE"}:
            return "UNAVAILABLE"
        if isinstance(observation.data, dict):
            if observation.data.get("is_mock") is True:
                return "MOCK"
            mode = str(observation.data.get("data_mode", "")).upper()
            if mode in {"LIVE", "TEST_FIXTURE", "MOCK", "UNAVAILABLE"}:
                return mode
        if any("mock" in item.source.lower() for item in observation.provenance):
            return "MOCK"
        if any("fixture" in item.source.lower() for item in observation.provenance):
            return "TEST_FIXTURE"
        return "LIVE"

    @staticmethod
    def _source_time(observation: Observation) -> datetime | None:
        for item in observation.provenance:
            parsed = StockResearchResultBuilder._datetime(item.as_of)
            if parsed is not None:
                return parsed
        if isinstance(observation.data, dict):
            for key in ("source_time", "as_of", "trade_date", "date"):
                parsed = StockResearchResultBuilder._datetime(observation.data.get(key))
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _first_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            for key in ("data", "items"):
                nested = value.get(key)
                if isinstance(nested, dict):
                    return nested
                if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                    return nested[0]
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
        return {}

    @staticmethod
    def _deep_value(value: Any, *names: str) -> Any:
        if isinstance(value, dict):
            for name in names:
                if name in value and value[name] is not None:
                    return value[name]
            for child in value.values():
                found = StockResearchResultBuilder._deep_value(child, *names)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = StockResearchResultBuilder._deep_value(child, *names)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _number(mapping: dict[str, Any], *names: str) -> float | None:
        for name in names:
            value = mapping.get(name)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    @classmethod
    def _number_deep(cls, value: Any, *names: str) -> float | None:
        found = cls._deep_value(value, *names)
        try:
            return float(found) if found is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _text_deep(cls, value: Any, *names: str) -> str | None:
        found = cls._deep_value(value, *names)
        return str(found) if found not in (None, "") else None

    @classmethod
    def _string_list_deep(cls, value: Any, *names: str) -> list[str]:
        found = cls._deep_value(value, *names)
        if not isinstance(found, list):
            return []
        return [str(item) for item in found if item not in (None, "")]

    @staticmethod
    def _json_value(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    @classmethod
    def _canonical(cls, value: Any) -> str:
        return json.dumps(cls._json_value(value), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value in (None, ""):
            return ""
        text = html.unescape(str(value))
        text = _HTML_TAG.sub(" ", text)
        text = _CONTROL.sub("", text)
        return " ".join(text.split())[:300]

    @staticmethod
    def _unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(item for item in values if item))
