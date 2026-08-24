"""Finance 对 M4 通用 Cognitive 内核的可插拔语言理解与续步适配。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from bdlh_runtime.cognitive.contracts import (
    CognitiveAction,
    CognitiveActionType,
    CommunicationPlan,
    CommunicationSection,
    InputEvent,
    InputEventType,
)
from bdlh_runtime.cognitive.plugin_gates import finance_skill_enabled as finance_skill_enabled
from bdlh_runtime.domains.contracts import DomainBudget, DomainOperation, DomainOutcome
from bdlh_runtime.runtime.turn_router import is_resume_signal

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
_REFERENCE_PATTERN = re.compile(r"(?:它|这只|该股|刚才那只|刚才的|上面那只)")
_KNOWLEDGE_PATTERN = re.compile(r"(?:什么是|解释一下|是什么意思|有何区别|怎么算|如何理解)")
_RESEARCH_PATTERN = re.compile(r"(?:今天|现在|走势|行情|表现|怎么样|估值|基本面|技术面|分析|研究|跌了|涨了|价格)")
_FOLLOWUP_PATTERN = re.compile(
    r"^(?:今天|现在|走势|行情|估值|基本面|技术面|表现|价格)?(?:呢|怎么样|如何|跌了多少|涨了多少)$"
)
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
    """受控会话实体表：进程内热缓存；可挂 Chat Session 持久化以跨重启继承指代。"""

    def __init__(
        self,
        *,
        max_reference_turn_gap: int = 6,
        persistence: VerifiedEntityPersistence | None = None,
    ) -> None:
        if max_reference_turn_gap < 1:
            raise ValueError("max_reference_turn_gap must be positive")
        self._entities: dict[tuple[str, str], VerifiedInstrumentEntity] = {}
        self._pending: dict[tuple[str, str], tuple[InstrumentCandidate, ...]] = {}
        self._turns: dict[tuple[str, str], int] = {}
        self._active_event: dict[tuple[str, str], str] = {}
        self._max_reference_turn_gap = max_reference_turn_gap
        self._persistence = persistence

    def attach_persistence(self, persistence: VerifiedEntityPersistence) -> None:
        self._persistence = persistence

    def begin_turn(self, event: InputEvent) -> int:
        key = (event.user_id, event.session_id)
        if self._active_event.get(key) != event.event_id:
            # 进程内首次见到该 session 时从 Data Plane 灌入；同进程后续轮次以本地热缓存为准。
            if key not in self._active_event:
                self._hydrate(key)
            self._turns[key] = self._turns.get(key, 0) + 1
            self._active_event[key] = event.event_id
            self._flush(key)
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

_GENERAL_CHAT_UNAVAILABLE_REASON = "当前对话能力暂不可用，请稍后重试。"


def _finance_skill_enabled(enabled_skills: frozenset[str]) -> bool:
    return finance_skill_enabled(enabled_skills)


class _KnowledgeResponder(Protocol):
    def answer(self, message: str) -> str: ...


class FinanceCognitiveSelector:
    """金融 Skill 插件适配器：仅在 GoalAction 判定需要金融能力后进入。

    不充当产品默认意图机。Skill 开关表示「允许使用金融插件」，不强制每条消息进金融。
    """

    def __init__(
        self,
        entity_store: InMemoryVerifiedEntityStore,
        *,
        knowledge_responder: _KnowledgeResponder | None = None,
    ) -> None:
        self._entity_store = entity_store
        self._knowledge_responder = knowledge_responder

    async def select(self, event: InputEvent, *, understood: object | None = None) -> CognitiveAction:
        del understood
        self._entity_store.begin_turn(event)
        if event.event_type == InputEventType.SCHEDULED_WAKEUP:
            return self._scheduled_wakeup_action(event)
        # 会话声明了 Skill 快照但未启用 finance：禁止金融域，普通对话即可。
        if event.enabled_skills is not None and not _finance_skill_enabled(event.enabled_skills):
            return self._general_chat_action(event.message)
        message = event.message.strip()
        if _is_stable_knowledge_question(message):
            return self._skill_knowledge_action(message)

        impact_action = self._impact_action(event, message)
        if impact_action is not None:
            return impact_action

        selected_candidate = self._entity_store.select_candidate(event, message)
        if selected_candidate is not None:
            self._entity_store.put(
                event,
                selected_candidate,
                confirmation_status="USER_SELECTED",
            )
            return self._research_action(event, selected_candidate)

        if _FOLLOWUP_PATTERN.fullmatch(message) or is_resume_signal(message):
            entity = self._entity_store.latest(event)
            if entity is not None:
                return self._research_action(event, entity.candidate)
            # 无已验证标的可续：不当成强制荐股，回普通对话。
            return self._general_chat_action(message)

        mention = self._extract_mention(event)
        if mention is None:
            # Skill 开启也不等于本轮必须做金融分析。
            return self._general_chat_action(message)

        if mention.mention_type == "REFERENCE":
            entity = self._entity_store.latest(event)
            if entity is None:
                return CognitiveAction(
                    action_type=CognitiveActionType.ASK_USER,
                    reason_code="REFERENCE_NOT_RESOLVED",
                    reason="当前对话中没有可安全继承的已验证标的。你想分析哪只股票？",
                )
            return self._research_action(event, entity.candidate)

        # NAME/CODE：仅在用户话里有金融意图时才解析，避免闲聊被当成荐股。
        if mention.mention_type == "NAME" and not _looks_like_finance_query(message):
            return self._general_chat_action(message)

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

    def _general_chat_action(self, message: str) -> CognitiveAction:
        """普通对话：走直接回答器，不派发金融域、不写死金融引导文案。"""
        if self._knowledge_responder is None:
            return CognitiveAction(
                action_type=CognitiveActionType.RESPOND,
                reason_code="GENERAL_CHAT_UNAVAILABLE",
                reason=_GENERAL_CHAT_UNAVAILABLE_REASON,
            )
        return CognitiveAction(
            action_type=CognitiveActionType.RESPOND,
            reason_code="GENERAL_CHAT",
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

    @staticmethod
    def _impact_action(event: InputEvent, message: str) -> CognitiveAction | None:
        """组合健康 / 目标规划可不依赖标的解析，直接走 Finance 影响意图。"""
        if _is_goal_planning_request(message):
            intent = FinancialIntent.GOAL_PLANNING
            reason_code = "GOAL_PLANNING"
            objective = "基于已确认目标与用户金融快照评估目标规划影响"
            ops = {
                DomainOperation.READ_PORTFOLIO,
                DomainOperation.READ_PROFILE,
                DomainOperation.READ_FINANCIAL_GOALS,
                DomainOperation.READ_MARKET_DATA,
            }
        elif _is_portfolio_impact_request(message):
            intent = FinancialIntent.PORTFOLIO_IMPACT
            reason_code = "PORTFOLIO_IMPACT"
            objective = "基于权威持仓与估值评估组合暴露面"
            ops = {
                DomainOperation.READ_PORTFOLIO,
                DomainOperation.READ_PROFILE,
                DomainOperation.READ_MARKET_DATA,
            }
        else:
            return None
        request = FinancialDomainRequest(
            request_id=f"{event.event_id}:{intent.value.lower()}",
            authenticated_user_id=event.user_id,
            objective=objective,
            authorized_operations=ops,
            budget=DomainBudget(tool_call_limit=12, runtime_seconds=60, model_call_limit=0),
            financial_intent=intent,
            instruments=[],
            requires_financial_snapshot=True,
        )
        return CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code=reason_code,
            reason=objective,
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
    def _research_action(event: InputEvent, candidate: InstrumentCandidate) -> CognitiveAction:
        needs_snapshot = _is_suitability_only_request(event.message)
        authorized = {
            DomainOperation.READ_MARKET_DATA,
            DomainOperation.READ_PUBLIC_RESEARCH,
            DomainOperation.RUN_ANALYSIS,
        }
        if needs_snapshot:
            authorized |= {
                DomainOperation.READ_PORTFOLIO,
                DomainOperation.READ_PROFILE,
            }
        request = FinancialDomainRequest(
            request_id=f"{event.event_id}:{'suitability' if needs_snapshot else 'research'}",
            authenticated_user_id=event.user_id,
            objective=(
                "对已验证证券标的执行 fail-closed 个性化风险匹配筛查前置"
                if needs_snapshot
                else "对已验证证券标的执行只读客观研究"
            ),
            authorized_operations=authorized,
            budget=DomainBudget(
                tool_call_limit=16 if needs_snapshot else 12,
                runtime_seconds=90 if needs_snapshot else 60,
                model_call_limit=0,
            ),
            financial_intent=FinancialIntent.STOCK_RESEARCH,
            instruments=[candidate.instrument],
            requires_financial_snapshot=needs_snapshot,
        )
        return CognitiveAction(
            action_type=CognitiveActionType.INVOKE_DOMAIN,
            reason_code="SUITABILITY" if needs_snapshot else "STOCK_RESEARCH",
            reason=(
                "对已验证标的执行适配性前置评估（ADR-004 未批准前仅 fail-closed）"
                if needs_snapshot
                else "对已验证标的执行客观研究"
            ),
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


_FINANCE_QUERY_CUES = re.compile(
    r"(?:股票|个股|证券|标的|行情|走势|估值|市盈率|市净率|研报|持仓|组合|"
    r"分析|研究|适合我|适不适合|跌了|涨了|价格|行情|怎么样|如何|今天|现在)"
)


def _looks_like_finance_query(message: str) -> bool:
    """有代码或金融意图词才视为金融提问；避免普通闲聊被当标的名。"""
    if _CODE_PATTERN.search(message) or _FINANCE_QUERY_CUES.search(message):
        return True
    # 「什么是贵州茅台」：知识前缀但带发行人，仍应解析标的（纯概念题已在上游分流）。
    return bool(message.startswith(("什么是", "解释一下")) and _candidate_name(message))


def _first_hint(message: str, mapping: dict[str, str]) -> str | None:
    return next((value for token, value in mapping.items() if token in message), None)


def _is_suitability_only_request(message: str) -> bool:
    """含适配意图即走 Suitability；研究词不再一刀切排除（可并存）。"""

    return bool(re.search(r"(?:适合我|适不适合|是否适合|匹配我的风险)", message))


def _is_portfolio_impact_request(message: str) -> bool:
    return bool(re.search(r"(?:持仓|组合健康|组合暴露|仓位集中|我的组合|组合风险|仓位结构)", message))


def _is_goal_planning_request(message: str) -> bool:
    return bool(re.search(r"(?:目标规划|理财目标|投资目标|财务目标|目标期限|规划一下目标)", message))


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
