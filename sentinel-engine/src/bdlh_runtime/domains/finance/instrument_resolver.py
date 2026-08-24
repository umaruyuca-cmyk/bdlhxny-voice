"""金融领域自有、经数据源校验的自然语言标的解析。"""

from __future__ import annotations

import asyncio
from typing import Any

from bdlh_runtime.contracts.observation import Observation
from bdlh_runtime.domains.contracts import (
    ConfidenceAssessment,
    DomainError,
    RequiredUserDecision,
)
from bdlh_runtime.tools.capabilities import CapabilityRegistry

from .authorization import FinanceCapabilityAuthorizationPolicy
from .contracts import (
    FinancialInstrument,
    InstrumentCandidate,
    InstrumentMention,
    InstrumentResolutionOutcome,
    InstrumentResolutionRequest,
)

RESOLVE_INSTRUMENT_CAPABILITY = "market.resolve_instrument"


class FinanceInstrumentResolver:
    """只通过已登记的市场能力与 Observation 输出解析标的。

    本切片刻意不做网页发现：发现结果若未经第二次结构化行情校验，
    不能安全确立标的身份。
    """

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        authorization: FinanceCapabilityAuthorizationPolicy,
        executor: Any,
    ) -> None:
        self._registry = registry
        self._authorization = authorization
        self._executor = executor

    async def resolve(self, request: InstrumentResolutionRequest) -> InstrumentResolutionOutcome:
        if not self._registry.contains(RESOLVE_INSTRUMENT_CAPABILITY):
            return self._unavailable(
                request, "RESOLVER_CAPABILITY_UNAVAILABLE", "The controlled instrument resolver is not registered"
            )
        if not self._authorization.is_allowed(RESOLVE_INSTRUMENT_CAPABILITY, request.authorized_operations):
            return self._unavailable(
                request,
                "REQUIRED_CAPABILITY_NOT_AUTHORIZED",
                "Instrument resolution requires READ_MARKET_DATA authorization",
            )
        if request.budget.tool_call_limit < 1:
            return self._unavailable(
                request, "BUDGET_EXHAUSTED", "Instrument resolution requires one tool-call budget unit"
            )

        try:
            async with asyncio.timeout(request.budget.runtime_seconds):
                observation = await self._executor.execute(
                    RESOLVE_INSTRUMENT_CAPABILITY,
                    {"symbol": request.mention.normalized_text},
                    request_id=request.request_id,
                )
        except TimeoutError:
            return self._unavailable(
                request, "RUNTIME_BUDGET_EXHAUSTED", "Instrument resolution exceeded its runtime budget", retryable=True
            )
        except Exception as exc:
            return self._unavailable(
                request,
                "INSTRUMENT_RESOLUTION_FAILED",
                f"Instrument resolver failed: {type(exc).__name__}",
                retryable=True,
            )

        if not isinstance(observation, Observation):
            return self._unavailable(
                request, "CAPABILITY_CONTRACT_VIOLATION", "Instrument resolver did not return an Observation"
            )
        if observation.capability != RESOLVE_INSTRUMENT_CAPABILITY:
            return self._unavailable(
                request, "CAPABILITY_CONTRACT_VIOLATION", "Instrument resolver response identity mismatch"
            )
        if observation.status in {"FAILED", "UNAVAILABLE"}:
            return self._unavailable(
                request,
                observation.error_code or "RESOLVER_UNAVAILABLE",
                observation.error_message or "Instrument resolver is unavailable",
                retryable=True,
            )
        if _is_non_production_observation(observation):
            return self._unavailable(
                request,
                "NON_PRODUCTION_DATA",
                "Mock or fixture instrument data cannot establish source-validated identity",
            )

        candidates = self._candidates(request.mention, observation, request)
        if not candidates:
            return InstrumentResolutionOutcome(
                request_id=request.request_id,
                domain="finance",
                status="WAITING_USER",
                resolution_status="NOT_FOUND",
                confidence=ConfidenceAssessment(
                    level="LOW",
                    reasons=["No source-validated instrument matched the mention"],
                    coverage_status="LIMITED",
                ),
                limitations=["No source-validated instrument candidate was returned"],
                required_user_decisions=[
                    RequiredUserDecision(
                        decision_id="instrument_identity",
                        question="未能验证该证券标的。请补充公司全称、市场或证券代码。",
                        reason="研究前必须唯一确定证券身份",
                    )
                ],
            )

        exact = [item for item in candidates if item.match_type != "FUZZY"]
        if len(candidates) == 1 and len(exact) == 1:
            return InstrumentResolutionOutcome(
                request_id=request.request_id,
                domain="finance",
                status="COMPLETE",
                resolution_status="RESOLVED",
                selected=candidates[0],
                candidates=candidates,
                confidence=ConfidenceAssessment(
                    level="HIGH",
                    reasons=["A single exact candidate was validated by the market resolver"],
                    coverage_status="COMPLETE",
                ),
            )
        return InstrumentResolutionOutcome(
            request_id=request.request_id,
            domain="finance",
            status="WAITING_USER",
            resolution_status="AMBIGUOUS",
            candidates=candidates,
            confidence=ConfidenceAssessment(
                level="LOW",
                reasons=["More than one candidate or only fuzzy matches were returned"],
                coverage_status="PARTIAL",
            ),
            limitations=["User confirmation is required before research can continue"],
            required_user_decisions=[
                RequiredUserDecision(
                    decision_id="instrument_candidate",
                    question="找到多个可能的证券标的，请选择一个："
                    + "；".join(
                        f"{item.instrument.name or item.canonical_symbol}（{item.canonical_symbol}，{item.exchange}）"
                        for item in candidates
                    ),
                    reason="多个候选均可能匹配当前提及",
                    allowed_choices=[f"{item.canonical_symbol}@{item.exchange}" for item in candidates],
                )
            ],
        )

    def _candidates(
        self, mention: InstrumentMention, observation: Observation, request: InstrumentResolutionRequest
    ) -> list[InstrumentCandidate]:
        source_refs = [f"{item.source}:{item.tool}" for item in observation.provenance]
        result: list[InstrumentCandidate] = []
        seen: set[tuple[str, str]] = set()
        for raw in _candidate_items(observation.data):
            candidate = _candidate_from_raw(raw, mention, source_refs)
            if candidate is None or candidate.instrument.instrument_type not in request.allowed_instrument_types:
                continue
            if mention.market_hint and candidate.instrument.market != mention.market_hint:
                continue
            if mention.exchange_hint and candidate.exchange != mention.exchange_hint:
                continue
            key = (candidate.canonical_symbol, candidate.exchange)
            if key not in seen:
                seen.add(key)
                result.append(candidate)
        return result[: request.max_candidates]

    @staticmethod
    def _unavailable(
        request: InstrumentResolutionRequest, code: str, message: str, *, retryable: bool = False
    ) -> InstrumentResolutionOutcome:
        return InstrumentResolutionOutcome(
            request_id=request.request_id,
            domain="finance",
            status="LIMITED",
            resolution_status="UNAVAILABLE",
            confidence=ConfidenceAssessment(level="LOW", reasons=[message], coverage_status="LIMITED"),
            errors=[DomainError(code=code, message=message, retryable=retryable)],
            limitations=[message],
        )


def _is_non_production_observation(observation: Observation) -> bool:
    markers = {
        str(observation.data.get("data_mode") or "").upper() if isinstance(observation.data, dict) else "",
        str(observation.data.get("source_type") or "").upper() if isinstance(observation.data, dict) else "",
        str(getattr(observation, "data_mode", "") or "").upper(),
    }
    if markers & {"MOCK", "TEST_FIXTURE"}:
        return True
    for record in observation.provenance:
        source = f"{record.source}:{record.tool}".lower()
        if "mock" in source or "fixture" in source or "test_fixture" in source:
            return True
    return False


def _candidate_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("candidates", "items", "results"):
        values = data.get(key)
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    return [data]


def _infer_cn_exchange(symbol: str) -> str | None:
    code = symbol.strip()
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith(("5", "6", "9")):
        return "SSE"
    if code.startswith(("0", "1", "3")):
        return "SZSE"
    return None


def _candidate_from_raw(
    raw: dict[str, Any], mention: InstrumentMention, default_source_refs: list[str]
) -> InstrumentCandidate | None:
    symbol = raw.get("canonical_symbol") or raw.get("symbol") or raw.get("code")
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    exchange = raw.get("exchange")
    if not isinstance(exchange, str) or not exchange.strip():
        exchange = _infer_cn_exchange(symbol.strip())
    if not isinstance(exchange, str) or not exchange.strip():
        return None
    instrument_type = raw.get("instrument_type", "stock")
    if instrument_type not in {"stock", "etf", "index", "fund", "bond"}:
        return None
    refs = raw.get("source_refs", default_source_refs)
    if not isinstance(refs, list) or not refs or not all(isinstance(item, str) and item for item in refs):
        return None
    inferred_match = {"CODE": "EXACT_CODE", "NAME": "EXACT_NAME", "ALIAS": "EXACT_ALIAS", "REFERENCE": "FUZZY"}[
        mention.mention_type
    ]
    match_type = raw.get("match_type")
    if match_type not in {"EXACT_CODE", "EXACT_NAME", "EXACT_ALIAS", "FUZZY"}:
        match_type = inferred_match
    return InstrumentCandidate(
        instrument=FinancialInstrument(
            symbol=symbol.strip(),
            name=raw.get("name") if isinstance(raw.get("name"), str) else None,
            instrument_type=instrument_type,
            market=raw.get("market") if isinstance(raw.get("market"), str) else "CN",
        ),
        canonical_symbol=symbol.strip(),
        exchange=exchange.strip(),
        currency=raw.get("currency") if isinstance(raw.get("currency"), str) else None,
        match_type=match_type,
        source_refs=refs,
    )
