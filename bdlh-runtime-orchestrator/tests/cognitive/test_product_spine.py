"""产品主轴集成：快路径 → Understand → GoalAction → 可选金融插件。"""

from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.goal_action_selector import GoalActionSelector
from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
from bdlh_runtime.cognitive.semantic_router import SemanticRouteSelector, build_kernel_router
from bdlh_runtime.domains.finance.cognitive_adapter import FinanceCognitiveSelector, InMemoryVerifiedEntityStore


class _Respond:
    def answer(self, message: str) -> str:
        return f"chat:{message}"


class _NoDomain:
    async def dispatch(self, request):  # noqa: ANN001
        raise AssertionError(f"不应派发领域: {type(request).__name__}")


@pytest.mark.asyncio
async def test_product_spine_chitchat_uses_fastpath_without_domain() -> None:
    respond = _Respond()
    app = CognitiveOrchestrator(
        selector=GoalActionSelector(
            finance=FinanceCognitiveSelector(InMemoryVerifiedEntityStore(), knowledge_responder=respond),
            respond=respond,
        ),
        fastpath=SemanticRouteSelector(build_kernel_router(), knowledge_responder=respond),
        dispatcher=_NoDomain(),
        enabled_domains=frozenset({"finance"}),
    )
    result = await app.run(
        InputEvent(event_id="e1", user_id="u1", session_id="s1", message="你好"),
    )
    assert result.response.audit_codes == ["SEMANTIC_CHITCHAT"]
    assert [item.action_type for item in result.state.action_history] == [CognitiveActionType.RESPOND]


@pytest.mark.asyncio
async def test_product_spine_external_non_finance_stays_chat_even_with_skill() -> None:
    respond = _Respond()
    app = CognitiveOrchestrator(
        selector=GoalActionSelector(
            finance=FinanceCognitiveSelector(InMemoryVerifiedEntityStore(), knowledge_responder=respond),
            respond=respond,
        ),
        fastpath=SemanticRouteSelector(build_kernel_router(), knowledge_responder=respond),
        dispatcher=_NoDomain(),
        enabled_domains=frozenset({"finance"}),
    )
    result = await app.run(
        InputEvent(
            event_id="e1",
            user_id="u1",
            session_id="s1",
            message="网上搜一下量子计算最新公开资料",
            enabled_skills=frozenset({"finance.stock-research"}),
        ),
    )
    assert result.response.audit_codes == ["GENERAL_CHAT"]
    assert result.response.message.startswith("chat:")
