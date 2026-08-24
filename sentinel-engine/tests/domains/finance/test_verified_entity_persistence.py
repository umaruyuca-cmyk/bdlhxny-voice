"""受控会话实体跨进程 hydrate / flush。"""

from __future__ import annotations

from bdlh_runtime.cognitive.contracts import InputEvent, InputEventType
from bdlh_runtime.domains.finance.cognitive_adapter import InMemoryVerifiedEntityStore
from bdlh_runtime.domains.finance.contracts import FinancialInstrument, InstrumentCandidate
from bdlh_runtime.infra.chat_sessions import (
    ChatSessionVerifiedEntityPersistence,
    InMemoryChatSessionStore,
)


def _event(message: str, *, event_id: str, session_id: str = "session-1") -> InputEvent:
    return InputEvent(
        event_id=event_id,
        run_id=f"run:{event_id}",
        user_id="7",
        session_id=session_id,
        message=message,
        event_type=InputEventType.USER_MESSAGE,
    )


def _candidate() -> InstrumentCandidate:
    return InstrumentCandidate(
        instrument=FinancialInstrument(symbol="600519", name="贵州茅台", market="CN"),
        canonical_symbol="600519",
        exchange="SSE",
        currency="CNY",
        match_type="EXACT_NAME",
        source_refs=["fixture:maotai"],
    )


def test_verified_entity_survives_process_local_store_restart() -> None:
    sessions = InMemoryChatSessionStore()
    sessions.ensure("session-1", "7")
    persistence = ChatSessionVerifiedEntityPersistence(sessions)

    first = InMemoryVerifiedEntityStore(persistence=persistence)
    first.put(_event("贵州茅台今天怎么样", event_id="e1"), _candidate())
    snapshot = sessions.get_verified_entity_state("session-1", "7")
    assert snapshot is not None
    assert snapshot["entity"]["candidate"]["canonical_symbol"] == "600519"

    # 模拟 Orchestrator 重启：全新进程内表，仅靠 Data Plane 快照。
    second = InMemoryVerifiedEntityStore(persistence=persistence)
    entity = second.latest(_event("它今天怎么样", event_id="e2"))
    assert entity is not None
    assert entity.candidate.canonical_symbol == "600519"
    assert entity.entity_ref == "instrument:600519@SSE"


def test_pending_candidates_also_round_trip_via_session_store() -> None:
    sessions = InMemoryChatSessionStore()
    sessions.ensure("session-1", "7")
    store = InMemoryVerifiedEntityStore(
        persistence=ChatSessionVerifiedEntityPersistence(sessions),
    )
    store.put_candidates(_event("平安", event_id="e1"), [_candidate()])

    revived = InMemoryVerifiedEntityStore(
        persistence=ChatSessionVerifiedEntityPersistence(sessions),
    )
    selected = revived.select_candidate(_event("选择 600519@SSE", event_id="e2"), "选择 600519@SSE")
    assert selected is not None
    assert selected.canonical_symbol == "600519"
