"""Finance 对 M4 通用 Cognitive 内核的可插拔语言理解与续步适配。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    CommunicationPlan,
    CommunicationSection,
    InputEvent,
    InputEventType,
)
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainOutcome

from .contracts import (
    FinancialDomainRequest,
    FinancialDomainOutcome,
    FinancialInstrument,
    FinancialIntent,
    InstrumentCandidate,
    InstrumentMention,
    InstrumentResolutionOutcome,
    InstrumentResolutionRequest,
)


_CODE_PATTERN = re.compile(r"(?<!\d)(?P<code>\d{6})(?!\d)")
_REFERENCE_PATTERN = re.compile(r"(?:它|这只|该股|刚才那只|刚才的|上面那只)")
_KNOWLEDGE_PATTERN = re.compile(r"(?:什么是|解释一下|是什么意思|有何区别|怎么算|如何理解)")
_RESEARCH_PATTERN = re.compile(
    r"(?:今天|现在|走势|行情|表现|怎么样|估值|基本面|技术面|分析|研究|跌了|涨了|价格)"
)
_FOLLOWUP_PATTERN = re.compile(
    r"^(?:今天|现在|走势|行情|估值|基本面|技术面|表现|价格)?(?:呢|怎么样|如何|跌了多少|涨了多少)$"
)
_MARKET_HINTS = {
    "A股": "CN", "沪市": "CN", "深市": "CN", "港股": "HK", "美股": "US",
}
_EXCHANGE_HINTS = {"上交所": "SSE", "深交所": "SZSE", "港交所": "HKEX"}


@dataclass(frozen=True)
class VerifiedInstrumentEntity:
    candidate: InstrumentCandidate
    entity_ref: str
    confirmation_status: Literal["SOURCE_VALIDATED", "USER_SELECTED"]
    verified_turn: int


class InMemoryVerifiedEntityStore:
    """M4 开发入口的进程内实体表；不冒充持久化 Checkpoint。"""

    def __init__(self, *, max_reference_turn_gap: int = 6) -> None:
        if max_reference_turn_gap < 1:
            raise ValueError("max_reference_turn_gap must be positive")
        self._entities: dict[tuple[str, str], VerifiedInstrumentEntity] = {}
        self._pending: dict[tuple[str, str], tuple[InstrumentCandidate, ...]] = {}
        self._turns: dict[tuple[str, str], int] = {}
        self._active_event: dict[tuple[str, str], str] = {}
        self._max_reference_turn_gap = max_reference_turn_gap

    def begin_turn(self, event: InputEvent) -> int:
        key = (event.user_id, event.session_id)
        if self._active_event.get(key) != event.event_id:
            self._turns[key] = self._turns.get(key, 0) + 1
            self._active_event[key] = event.event_id
        return self._turns[key]

    def put(
        self,
        event: InputEvent,
        candidate: InstrumentCandidate,
        *,
        confirmation_status: Literal["SOURCE_VALIDATED", "USER_SELECTED"] = "SOURCE_VALIDATED",
    ) -> str:
        turn = self.begin_turn(event)
        entity_ref = f"instrument:{candidate.canonical_symbol}@{candidate.exchange}"
        self._entities[(event.user_id, event.session_id)] = VerifiedInstrumentEntity(
            candidate=candidate,
            entity_ref=entity_ref,
            confirmation_status=confirmation_status,
            verified_turn=turn,
        )
        self._pending.pop((event.user_id, event.session_id), None)
        return entity_ref

    def latest(self, event: InputEvent) -> VerifiedInstrumentEntity | None:
        turn = self.begin_turn(event)
        entity = self._entities.get((event.user_id, event.session_id))
        if entity is None or turn - entity.verified_turn > self._max_reference_turn_gap:
            return None
        return entity

    def put_candidates(
        self, event: InputEvent, candidates: list[InstrumentCandidate]
    ) -> None:
        self._pending[(event.user_id, event.session_id)] = tuple(candidates[:5])

    def select_candidate(
        self, event: InputEvent, message: str
    ) -> InstrumentCandidate | None:
        pending = self._pending.get((event.user_id, event.session_id), ())
        normalized = message.strip().upper()
        matches = [
            item
            for item in pending
            if item.canonical_symbol.upper() in normalized
            or f"{item.canonical_symbol}@{item.exchange}".upper() in normalized
            or (item.instrument.name and item.instrument.name in message)
        ]
        return matches[0] if len(matches) == 1 else None


class FinanceCognitiveSelector:
    """确定性提取金融实体提及；不生成未经验证的 canonical symbol。"""

    def __init__(self, entity_store: InMemoryVerifiedEntityStore) -> None:
        self._entity_store = entity_store

    async def select(self, event: InputEvent) -> CognitiveAction:
        self._entity_store.begin_turn(event)
        if event.event_type == InputEventType.SCHEDULED_WAKEUP:
            return self._scheduled_wakeup_action(event)
        message = event.message.strip()
        if _is_stable_knowledge_question(message):
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="STABLE_FINANCIAL_KNOWLEDGE",
                reason=_knowledge_answer(message),
            )

        selected_candidate = self._entity_store.select_candidate(event, message)
        if selected_candidate is not None:
            self._entity_store.put(
                event,
                selected_candidate,
                confirmation_status="USER_SELECTED",
            )
            return self._research_action(event, selected_candidate)

        if _FOLLOWUP_PATTERN.fullmatch(message):
            entity = self._entity_store.latest(event)
            if entity is not None:
                return self._research_action(event, entity.candidate)

        mention = self._extract_mention(event)
        if mention is None:
            return CognitiveAction(
                action_type=CognitiveActionType.ASK_USER,
                reason_code="INSTRUMENT_REQUIRED",
                reason="你想分析哪只股票？可以直接提供公司名称、简称或证券代码。",
            )

        if mention.mention_type == "REFERENCE":
            entity = self._entity_store.latest(event)
            if entity is None:
                return CognitiveAction(
                    action_type=CognitiveActionType.ASK_USER,
                    reason_code="REFERENCE_NOT_RESOLVED",
                    reason="当前对话中没有可安全继承的已验证标的。你想分析哪只股票？",
                )
            return self._research_action(event, entity.candidate)

        resolution = InstrumentResolutionRequest(
            request_id=f"{event.event_id}:resolve",
            authenticated_user_id=event.user_id,
            objective="通过受控证券主数据解析用户提及的标的",
            authorized_operations={DomainOperation.READ_MARKET_DATA},
            budget=DomainBudget(tool_call_limit=1, runtime_seconds=10),
            mention=mention,
        )
        return CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="RESOLVE_INSTRUMENT",
            reason="先通过金融领域边界验证证券身份",
            domain_request=resolution,
        )

    @staticmethod
    def _scheduled_wakeup_action(event: InputEvent) -> CognitiveAction:
        """任务唤醒只接受服务端生成、携带已验证证券代码的固定格式。"""

        code_match = _CODE_PATTERN.search(event.message)
        if code_match is None:
            return CognitiveAction(
                action_type=CognitiveActionType.ASK_USER,
                reason_code="TASK_INSTRUMENT_REQUIRED",
                reason="持续任务缺少可验证的证券代码，已停止本次唤醒。",
            )
        symbol = code_match.group("code")
        request = FinancialDomainRequest(
            request_id=f"{event.event_id}:research",
            authenticated_user_id=event.user_id,
            objective="为已确认的价格观察任务重新获取当前市场事实",
            authorized_operations={
                DomainOperation.READ_MARKET_DATA,
                DomainOperation.RUN_ANALYSIS,
            },
            budget=DomainBudget(tool_call_limit=3, runtime_seconds=30, model_call_limit=0),
            financial_intent=FinancialIntent.STOCK_RESEARCH,
            instruments=[FinancialInstrument(symbol=symbol, market="CN")],
        )
        return CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="TASK_PRICE_OBSERVATION_REFRESH",
            reason="重新获取任务标的的当前价格事实",
            related_goal_ids=[event.task_id] if event.task_id else [],
            domain_request=request,
        )

    def _extract_mention(self, event: InputEvent) -> InstrumentMention | None:
        message = event.message.strip()
        code_match = _CODE_PATTERN.search(message)
        if code_match:
            code = code_match.group("code")
            return InstrumentMention(
                raw_text=code,
                normalized_text=code,
                mention_type="CODE",
                market_hint=_first_hint(message, _MARKET_HINTS),
                exchange_hint=_first_hint(message, _EXCHANGE_HINTS),
            )
        reference = _REFERENCE_PATTERN.search(message)
        if reference:
            entity = self._entity_store.latest(event)
            return InstrumentMention(
                raw_text=reference.group(0),
                normalized_text=reference.group(0),
                mention_type="REFERENCE",
                context_entity_ref=entity.entity_ref if entity else "unresolved",
            )
        normalized = _candidate_name(message)
        if not normalized:
            return None
        return InstrumentMention(
            raw_text=normalized,
            normalized_text=normalized,
            mention_type="NAME",
            market_hint=_first_hint(message, _MARKET_HINTS),
            exchange_hint=_first_hint(message, _EXCHANGE_HINTS),
        )

    @staticmethod
    def _research_action(
        event: InputEvent, candidate: InstrumentCandidate
    ) -> CognitiveAction:
        # SuitabilityEngine 在 M1–M3 未启用；禁止路由到已废弃意图。
        if _is_suitability_only_request(event.message):
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="SUITABILITY_NOT_ENABLED",
                reason=(
                    f"个性化适配性评估尚未启用。"
                    f"我可以先对 {candidate.instrument.name or candidate.canonical_symbol} "
                    f"做客观只读研究；请直接问走势、估值或基本面。"
                ),
            )
        request = FinancialDomainRequest(
            request_id=f"{event.event_id}:research",
            authenticated_user_id=event.user_id,
            objective="对已验证证券标的执行只读客观研究",
            authorized_operations={
                DomainOperation.READ_MARKET_DATA,
                DomainOperation.READ_PUBLIC_RESEARCH,
                DomainOperation.RUN_ANALYSIS,
            },
            budget=DomainBudget(tool_call_limit=12, runtime_seconds=60, model_call_limit=0),
            financial_intent=FinancialIntent.STOCK_RESEARCH,
            instruments=[candidate.instrument],
            requires_financial_snapshot=False,
        )
        return CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="STOCK_RESEARCH",
            reason="对已验证标的执行客观研究",
            domain_request=request,
        )


class FinanceCognitiveContinuation:
    """只负责 Finance 解析成功后的领域续步；最终表达仍由通用内核完成。"""

    def __init__(self, entity_store: InMemoryVerifiedEntityStore) -> None:
        self._entity_store = entity_store

    async def continue_after(
        self, *, event: InputEvent, outcome: DomainOutcome
    ) -> CognitiveAction | CommunicationPlan | None:
        if isinstance(outcome, InstrumentResolutionOutcome):
            if outcome.resolution_status == "AMBIGUOUS":
                self._entity_store.put_candidates(event, outcome.candidates)
                return None
            if outcome.resolution_status != "RESOLVED" or outcome.selected is None:
                return None
            self._entity_store.put(event, outcome.selected)
            return FinanceCognitiveSelector._research_action(event, outcome.selected)
        if isinstance(outcome, FinancialDomainOutcome) and outcome.suitability:
            assessment = outcome.suitability
            required = outcome.suitability.required_conditions
            if required:
                return CommunicationPlan(
                    response_kind="ASK_USER",
                    response_structure="SUITABILITY",
                    summary=required[0].description,
                    required_fields=[item.condition_id for item in required],
                    evidence_refs=list(outcome.suitability.evidence_refs),
                    limitations=list(outcome.limitations) + list(outcome.suitability.limitations),
                    risk_disclosures=list(outcome.suitability.reasons),
                    next_steps=[item.description for item in required],
                )
            summary = f"个性化风险匹配筛查结果：{assessment.result}。"
            sections = [CommunicationSection(
                section_type="SUMMARY",
                title="风险匹配筛查",
                items=[summary],
            )]
            if assessment.reasons:
                sections.append(CommunicationSection(
                    section_type="FINDINGS",
                    title="筛查理由",
                    items=list(assessment.reasons),
                ))
            limitations = list(dict.fromkeys(
                list(outcome.limitations) + list(assessment.limitations)
            ))
            if limitations:
                sections.append(CommunicationSection(
                    section_type="LIMITATIONS",
                    title="限制",
                    items=limitations,
                ))
            return CommunicationPlan(
                response_kind=("LIMITED" if limitations else "DOMAIN_RESULT"),
                response_structure="SUITABILITY",
                summary=summary,
                sections=sections,
                evidence_refs=list(assessment.evidence_refs),
                limitations=limitations,
                risk_disclosures=list(assessment.reasons),
            )
        return None


def _candidate_name(message: str) -> str | None:
    cleaned = message
    for token in (*_MARKET_HINTS, *_EXCHANGE_HINTS):
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(
        r"(?:请问|麻烦|帮我|帮忙|看一下|看看|分析一下|分析|研究一下|研究|今天|现在|目前|"
        r"的?走势|的?行情|的?表现|的?估值|基本面|技术面|怎么样|如何|跌了多少|涨了多少|价格)",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"[，。！？、,.!?\s]+", "", cleaned)
    if not cleaned or cleaned in {"股票", "公司", "上市公司", "证券", "标的"}:
        return None
    if len(cleaned) > 32:
        return None
    return cleaned


def _first_hint(message: str, mapping: dict[str, str]) -> str | None:
    return next((value for token, value in mapping.items() if token in message), None)


def _knowledge_answer(message: str) -> str:
    if "市盈率" in message or "PE" in message.upper():
        return "市盈率（PE）是股价相对每股收益的倍数，常用于比较盈利估值；应结合盈利质量、行业与周期看，不能单凭倍数高低判断贵或便宜。"
    if "市净率" in message or "PB" in message.upper():
        return "市净率（PB）是市值相对净资产的倍数，常用于重资产或金融类公司比较；资产质量和盈利能力会显著影响其解释。"
    if "估值" in message:
        return "估值是用盈利、现金流、资产或可比公司等方法衡量证券价格相对基本面的水平；不同方法依赖不同假设，通常需要交叉验证。"
    return "这个问题属于稳定金融知识，可从定义、适用条件、局限和常见误区四个方面理解；如需实时标的数据，请同时给出公司名称、简称或证券代码。"


def _is_suitability_only_request(message: str) -> bool:
    if not re.search(r"(?:适合我|适不适合|是否适合|匹配我的风险)", message):
        return False
    # 若用户同时要求市场研究，优先走客观研究。
    return not bool(_RESEARCH_PATTERN.search(message))


def _is_stable_knowledge_question(message: str) -> bool:
    """仅把纯概念问答当知识题；出现标的提及时必须走解析。"""
    if _CODE_PATTERN.search(message):
        return False
    looks_like_knowledge = message.startswith(("什么是", "解释一下")) or bool(
        re.search(r"(?:是什么意思|有何区别|如何理解)$", message)
    )
    if not looks_like_knowledge:
        return False
    remainder = re.sub(r"^(?:什么是|解释一下)", "", message)
    remainder = re.sub(r"(?:是什么意思|有何区别|如何理解)$", "", remainder)
    remainder = re.sub(
        r"(?:的)?(?:市盈率|市净率|市销率|估值|换手率|基本面|技术面|PE|PB|PS|ROE|MACD)",
        " ",
        remainder,
        flags=re.IGNORECASE,
    )
    return _candidate_name(remainder) is None
