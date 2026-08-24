"""Finance 对 M4 通用 Cognitive 内核的可插拔语言理解与续步适配。

LLM 通过 ``UnderstandOutput.action`` 直接输出工具调用指令，本适配器只做
参数到领域请求的映射，不做意图分类。
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from bdlh_runtime.cognitive.contracts import (
    RESPOND_UNAVAILABLE_REASON,
    CognitiveAction,
    CognitiveActionType,
    CommunicationPlan,
    CommunicationSection,
    InputEvent,
    InputEventType,
)
from bdlh_runtime.cognitive.goal_schema import UnderstandOutput
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainOutcome

from .contracts import (
    FinancialDomainOutcome,
    FinancialDomainRequest,
    FinancialInstrument,
    FinancialIntent,
    InstrumentCandidate,
    InstrumentMention,
    InstrumentResolutionOutcome,
    InstrumentResolutionRequest,
)

_CODE_PATTERN = re.compile(r"(?<!\d)(?P<code>\d{6})(?!\d)")
_MARKET_HINTS = {
    "A股": "CN",
    "沪市": "CN",
    "深市": "CN",
    "港股": "HK",
    "美股": "US",
}
_EXCHANGE_HINTS = {"上交所": "SSE", "深交所": "SZSE", "港交所": "HKEX"}


@dataclass(frozen=True)
class VerifiedInstrumentEntity:
    candidate: InstrumentCandidate
    entity_ref: str
    confirmation_status: Literal["SOURCE_VALIDATED", "USER_SELECTED"]
    verified_turn: int


class VerifiedEntityPersistence(Protocol):
    """会话实体快照读写；由 Chat Session Data Plane 实现，不冒充 L0 Checkpoint。"""

    def load(self, *, user_id: str, session_id: str) -> dict[str, Any] | None: ...

    def save(self, *, user_id: str, session_id: str, state: dict[str, Any] | None) -> None: ...


class InMemoryVerifiedEntityStore:
    """受控会话实体表：单 worker 进程内热缓存，不跨副本共享。

    会话键按 LRU 淘汰；可挂 Chat Session 持久化以跨重启继承指代。
    """

    def __init__(
        self,
        *,
        max_reference_turn_gap: int = 6,
        max_sessions: int = 512,
        persistence: VerifiedEntityPersistence | None = None,
    ) -> None:
        if max_reference_turn_gap < 1:
            raise ValueError("max_reference_turn_gap must be positive")
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self._entities: dict[tuple[str, str], VerifiedInstrumentEntity] = {}
        self._pending: dict[tuple[str, str], tuple[InstrumentCandidate, ...]] = {}
        self._turns: dict[tuple[str, str], int] = {}
        self._active_event: dict[tuple[str, str], str] = {}
        self._lru: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._max_reference_turn_gap = max_reference_turn_gap
        self._max_sessions = max_sessions
        self._persistence = persistence

    def attach_persistence(self, persistence: VerifiedEntityPersistence) -> None:
        self._persistence = persistence

    def begin_turn(self, event: InputEvent) -> int:
        key = (event.user_id, event.session_id)
        self._touch(key)
        if self._active_event.get(key) != event.event_id:
            # 进程内首次见到该 session 时从 Data Plane 灌入；同进程后续轮次以本地热缓存为准。
            if key not in self._active_event:
                self._hydrate(key)
            self._turns[key] = self._turns.get(key, 0) + 1
            self._active_event[key] = event.event_id
            self._flush(key)
        return self._turns[key]

    def _touch(self, key: tuple[str, str]) -> None:
        self._lru[key] = None
        self._lru.move_to_end(key)
        while len(self._lru) > self._max_sessions:
            stale, _ = self._lru.popitem(last=False)
            self._entities.pop(stale, None)
            self._pending.pop(stale, None)
            self._turns.pop(stale, None)
            self._active_event.pop(stale, None)

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
        self._flush((event.user_id, event.session_id))
        return entity_ref

    def latest(self, event: InputEvent) -> VerifiedInstrumentEntity | None:
        turn = self.begin_turn(event)
        entity = self._entities.get((event.user_id, event.session_id))
        if entity is None or turn - entity.verified_turn > self._max_reference_turn_gap:
            return None
        return entity

    def put_candidates(self, event: InputEvent, candidates: list[InstrumentCandidate]) -> None:
        self.begin_turn(event)
        self._pending[(event.user_id, event.session_id)] = tuple(candidates[:5])
        self._flush((event.user_id, event.session_id))

    def select_candidate(self, event: InputEvent, message: str) -> InstrumentCandidate | None:
        self.begin_turn(event)
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

    def export_state(self, *, user_id: str, session_id: str) -> dict[str, Any] | None:
        key = (user_id, session_id)
        entity = self._entities.get(key)
        pending = self._pending.get(key, ())
        turn = self._turns.get(key)
        if entity is None and not pending and not turn:
            return None
        payload: dict[str, Any] = {"schema_version": "verified-entity.v1", "turn": int(turn or 0)}
        if entity is not None:
            payload["entity"] = {
                "entity_ref": entity.entity_ref,
                "confirmation_status": entity.confirmation_status,
                "verified_turn": entity.verified_turn,
                "candidate": entity.candidate.model_dump(mode="json"),
            }
        if pending:
            payload["pending_candidates"] = [item.model_dump(mode="json") for item in pending]
        return payload

    def _hydrate(self, key: tuple[str, str]) -> None:
        if self._persistence is None:
            return
        user_id, session_id = key
        try:
            snapshot = self._persistence.load(user_id=user_id, session_id=session_id)
        except Exception:
            return
        if not isinstance(snapshot, dict):
            return
        turn = snapshot.get("turn")
        if isinstance(turn, int) and turn >= 0:
            self._turns[key] = turn
        entity_payload = snapshot.get("entity")
        if isinstance(entity_payload, dict):
            try:
                candidate = InstrumentCandidate.model_validate(entity_payload.get("candidate"))
                status = entity_payload.get("confirmation_status") or "SOURCE_VALIDATED"
                if status not in {"SOURCE_VALIDATED", "USER_SELECTED"}:
                    status = "SOURCE_VALIDATED"
                verified_turn = int(entity_payload.get("verified_turn") or turn or 0)
                entity_ref = str(
                    entity_payload.get("entity_ref") or f"instrument:{candidate.canonical_symbol}@{candidate.exchange}"
                )
                self._entities[key] = VerifiedInstrumentEntity(
                    candidate=candidate,
                    entity_ref=entity_ref,
                    confirmation_status=status,  # type: ignore[arg-type]
                    verified_turn=verified_turn,
                )
            except Exception:
                self._entities.pop(key, None)
        pending_payload = snapshot.get("pending_candidates")
        if isinstance(pending_payload, list):
            restored: list[InstrumentCandidate] = []
            for item in pending_payload[:5]:
                try:
                    restored.append(InstrumentCandidate.model_validate(item))
                except Exception:
                    continue
            if restored:
                self._pending[key] = tuple(restored)
            else:
                self._pending.pop(key, None)
        else:
            self._pending.pop(key, None)

    def _flush(self, key: tuple[str, str]) -> None:
        if self._persistence is None:
            return
        user_id, session_id = key
        try:
            self._persistence.save(
                user_id=user_id,
                session_id=session_id,
                state=self.export_state(user_id=user_id, session_id=session_id),
            )
        except Exception:
            # 持久化失败不得阻断本轮 Cognitive；下一轮可再试。
            return


_SKILL_KNOWLEDGE_UNAVAILABLE_REASON = "当前知识回答能力暂不可用，请稍后重试。"
_KNOWN_SKILL_IDS = frozenset(
    {
        "stock-research",
        "portfolio-health",
        "suitability-evaluation",
    }
)


class _KnowledgeResponder(Protocol):
    def answer(self, message: str) -> str: ...


class FinanceCognitiveSelector:
    """finance Skill 的工具 handler。只在 LLM 选中对应工具后进入，不做意图分类。"""

    def __init__(
        self,
        entity_store: InMemoryVerifiedEntityStore,
        *,
        knowledge_responder: _KnowledgeResponder | None = None,
    ) -> None:
        self._entity_store = entity_store
        self._knowledge_responder = knowledge_responder

    async def select(self, event: InputEvent, *, understood: object | None = None) -> CognitiveAction:
        parsed = understood if isinstance(understood, UnderstandOutput) else None
        self._entity_store.begin_turn(event)
        if event.event_type == InputEventType.SCHEDULED_WAKEUP:
            return self._scheduled_wakeup_action(event)
        if not _skill_enabled(event.enabled_skills):
            return self._respond_action(event.message)

        # LLM 主导：直接按 action.tool 路由，不做意图分类
        if parsed is None or parsed.action is None:
            return CognitiveAction(
                action_type=CognitiveActionType.ASK_USER,
                reason_code="TOOL_ARGUMENT_REQUIRED",
                reason="请补充证券代码、公司名称或简称，或明确您要进行的操作。",
            )

        tool = parsed.action.tool
        params = parsed.action.parameters

        # 从 action.parameters 提取标的（Function Calling 风格）
        symbol = params.get("symbol") or params.get("instrument")
        symbol = symbol.strip() if isinstance(symbol, str) and symbol.strip() else None

        if tool == "stock-research":
            if symbol is None:
                return CognitiveAction(
                    action_type=CognitiveActionType.ASK_USER,
                    reason_code="TOOL_ARGUMENT_REQUIRED",
                    reason="请补充证券代码、公司名称或简称。",
                )
            return self._research_action(event, symbol, parsed)

        if tool == "portfolio-health":
            return self._impact_action(event, FinancialIntent.PORTFOLIO_IMPACT, parsed)

        if tool == "suitability-evaluation":
            return self._impact_action(event, FinancialIntent.SUITABILITY, parsed)

        # 未知工具（不应发生，白名单已校验）
        return CognitiveAction(
            action_type=CognitiveActionType.ASK_USER,
            reason_code="TOOL_ARGUMENT_REQUIRED",
            reason=f"暂不支持工具 {tool}，请换一个问题。",
        )

    def _respond_action(self, message: str) -> CognitiveAction:
        """工具不可用或无需域执行时，回到 Agent 直接回答。"""
        if self._knowledge_responder is None:
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="RESPOND_UNAVAILABLE",
                reason=RESPOND_UNAVAILABLE_REASON,
            )
        return CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="RESPOND",
            reason=self._knowledge_responder.answer(message.strip()),
        )

    def _skill_knowledge_action(self, message: str) -> CognitiveAction:
        """Skill 已授权后的知识分析：走知识回答器，禁止硬编码词典。"""
        if self._knowledge_responder is None:
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="SKILL_KNOWLEDGE_UNAVAILABLE",
                reason=_SKILL_KNOWLEDGE_UNAVAILABLE_REASON,
            )
        return CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="SKILL_KNOWLEDGE",
            reason=self._knowledge_responder.answer(message),
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

    def _impact_action(
        self,
        event: InputEvent,
        intent: FinancialIntent,
        understood: UnderstandOutput,
    ) -> CognitiveAction:
        """按 LLM 指定的意图构造领域请求。"""
        instruments: list[FinancialInstrument] = []
        if intent == FinancialIntent.SUITABILITY:
            # 适配性需要标的：从 action.parameters 或 entities 提取
            symbol = understood.action.parameters.get("symbol") if understood.action else None
            if not symbol and understood.entities.instruments:
                symbol = understood.entities.instruments[0]
            if symbol:
                instruments.append(FinancialInstrument(symbol=str(symbol), market="CN"))

        if intent == FinancialIntent.GOAL_PLANNING:
            reason_code = "GOAL_PLANNING"
            objective = "基于已确认目标与用户金融快照评估目标规划影响"
            ops = {
                DomainOperation.READ_PORTFOLIO,
                DomainOperation.READ_PROFILE,
                DomainOperation.READ_FINANCIAL_GOALS,
                DomainOperation.READ_MARKET_DATA,
            }
        elif intent == FinancialIntent.PORTFOLIO_IMPACT:
            reason_code = "PORTFOLIO_IMPACT"
            objective = "基于权威持仓与估值评估组合暴露面"
            ops = {
                DomainOperation.READ_PORTFOLIO,
                DomainOperation.READ_PROFILE,
                DomainOperation.READ_MARKET_DATA,
            }
        elif intent == FinancialIntent.SUITABILITY:
            reason_code = "SUITABILITY"
            objective = "基于用户金融快照执行个性化风险匹配筛查"
            ops = {
                DomainOperation.READ_PORTFOLIO,
                DomainOperation.READ_PROFILE,
                DomainOperation.READ_MARKET_DATA,
            }
        else:
            raise ValueError(f"不支持的 impact 意图: {intent}")

        request = FinancialDomainRequest(
            request_id=f"{event.event_id}:{intent.value.lower()}",
            authenticated_user_id=event.user_id,
            objective=objective,
            authorized_operations=ops,
            budget=DomainBudget(tool_call_limit=12, runtime_seconds=60, model_call_limit=0),
            financial_intent=intent,
            instruments=instruments,
            requires_financial_snapshot=True,
        )
        return CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code=reason_code,
            reason=objective,
            domain_request=request,
        )

    def _research_action(
        self,
        event: InputEvent,
        symbol: str,
        understood: UnderstandOutput,
    ) -> CognitiveAction:
        """按 LLM 提取的标的构造研究请求。"""
        # 检查是否与已验证实体冲突
        llm_codes = [code for code in understood.entities.instruments if _CODE_PATTERN.fullmatch(code)]
        if symbol not in llm_codes and llm_codes:
            return CognitiveAction(
                action_type=CognitiveActionType.ASK_USER,
                reason_code="INSTRUMENT_CONFLICT",
                reason=f"参数标的 {symbol} 与立案标的 {llm_codes[0]} 不一致，请确认。",
            )

        mention = InstrumentMention(
            raw_text=symbol,
            normalized_text=symbol,
            mention_type="CODE" if _CODE_PATTERN.fullmatch(symbol) else "NAME",
            market_hint=_first_hint(event.message, _MARKET_HINTS),
            exchange_hint=_first_hint(event.message, _EXCHANGE_HINTS),
        )

        # 先走标的解析，验证后再研究
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
            # 构造研究请求（resolution 已验证标的，直接研究）
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
                instruments=[outcome.selected.instrument],
                requires_financial_snapshot=False,
            )
            return CognitiveAction(
                action_type=CognitiveActionType.INVOKE_DOMAIN,
                reason_code="STOCK_RESEARCH",
                reason="对已验证标的执行客观研究",
                domain_request=request,
            )
        if isinstance(outcome, FinancialDomainOutcome) and outcome.suitability:
            assessment = outcome.suitability
            required = list(outcome.suitability.required_conditions)
            user_actionable = [
                item
                for item in required
                if item.condition_id
                not in {
                    "SUITABILITY_RULE_SET_APPROVAL_REQUIRED",
                    "SUITABILITY_CONDITIONS_PRESENT",
                }
            ]
            if user_actionable:
                next_steps = [item.description for item in user_actionable]
                needs_facts = (
                    any(item.condition_id == "USER_FACTS_CONFIRMATION_REQUIRED" for item in user_actionable)
                    or assessment.result == "INSUFFICIENT_INFORMATION"
                )
                if needs_facts:
                    next_steps.extend(
                        [
                            "打开金融资料确认",
                            "换一个新问题",
                        ]
                    )
                else:
                    next_steps.extend(["继续", "换一个新问题"])
                return CommunicationPlan(
                    response_kind="ASK_USER",
                    response_structure="SUITABILITY",
                    summary=user_actionable[0].description,
                    required_fields=[item.condition_id for item in user_actionable],
                    evidence_refs=list(outcome.suitability.evidence_refs),
                    limitations=list(outcome.limitations) + list(outcome.suitability.limitations),
                    risk_disclosures=list(outcome.suitability.reasons),
                    next_steps=list(dict.fromkeys(next_steps)),
                )
            summary = f"个性化风险匹配筛查结果：{assessment.result}。"
            sections = [
                CommunicationSection(
                    section_type="SUMMARY",
                    title="风险匹配筛查",
                    items=[summary],
                )
            ]
            if assessment.reasons:
                sections.append(
                    CommunicationSection(
                        section_type="FINDINGS",
                        title="筛查理由",
                        items=list(assessment.reasons),
                    )
                )
            limitations = list(
                dict.fromkeys(
                    list(outcome.limitations) + list(assessment.limitations) + [item.description for item in required]
                )
            )
            if limitations:
                sections.append(
                    CommunicationSection(
                        section_type="LIMITATIONS",
                        title="限制",
                        items=limitations,
                    )
                )
            return CommunicationPlan(
                response_kind="LIMITED",
                response_structure="SUITABILITY",
                summary=summary,
                sections=sections,
                evidence_refs=list(assessment.evidence_refs),
                limitations=limitations,
                risk_disclosures=list(assessment.reasons),
                next_steps=["可继续追问该标的客观研究，或补充风险偏好与持仓后再做适配筛查"],
            )
        if isinstance(outcome, FinancialDomainOutcome) and (
            outcome.portfolio_impact is not None or outcome.goal_impact is not None
        ):
            return _impact_communication_plan(outcome)
        return None


def _impact_communication_plan(outcome: FinancialDomainOutcome) -> CommunicationPlan:
    evidence = [
        reason.removeprefix("impact evidence: ").strip()
        for reason in outcome.confidence.reasons
        if reason.startswith("impact evidence:")
    ]
    evidence_refs = [part for chunk in evidence for part in chunk.split(", ") if part]
    sections: list[CommunicationSection] = []
    if outcome.portfolio_impact is not None:
        exposure = outcome.portfolio_impact.current_exposure
        items = [f"{key}={value:.2f}%" for key, value in sorted(exposure.items())] or ["暂无可用持仓权重"]
        sections.append(CommunicationSection(section_type="FINDINGS", title="组合暴露", items=items))
        summary = "已完成组合暴露面评估。"
        structure = "PORTFOLIO_IMPACT"
    else:
        assert outcome.goal_impact is not None
        items = list(outcome.goal_impact.reasons) or ["暂无目标影响结论"]
        if outcome.goal_impact.affected_goal_ids:
            items = [
                f"影响目标：{', '.join(outcome.goal_impact.affected_goal_ids)}",
                f"影响级别：{outcome.goal_impact.impact_level}",
                *items,
            ]
        sections.append(CommunicationSection(section_type="FINDINGS", title="目标规划影响", items=items))
        summary = f"目标规划影响级别：{outcome.goal_impact.impact_level}。"
        structure = "GOAL_PLANNING"
    if outcome.limitations:
        sections.append(CommunicationSection(section_type="LIMITATIONS", title="限制", items=list(outcome.limitations)))
    kind = "ANSWER" if outcome.status == "COMPLETE" else "LIMITED"
    return CommunicationPlan(
        response_kind=kind,  # type: ignore[arg-type]
        response_structure=structure,
        summary=summary,
        sections=sections,
        evidence_refs=evidence_refs,
        limitations=list(outcome.limitations),
        next_steps=["打开金融资料确认", "换一个新问题"],
    )


def _skill_enabled(enabled_skills: frozenset[str] | None) -> bool:
    if not enabled_skills:
        return False
    return any(item.split(".", 1)[-1] in _KNOWN_SKILL_IDS for item in enabled_skills)


def _first_hint(message: str, mapping: dict[str, str]) -> str | None:
    return next((value for token, value in mapping.items() if token in message), None)
