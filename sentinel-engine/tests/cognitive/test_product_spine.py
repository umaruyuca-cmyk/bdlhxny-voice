"""产品主轴集成：快路径 → Understand → 工具选择 → 可选 Skill handler。"""

from __future__ import annotations

import pytest

from bdlh_runtime.cognitive.contracts import CognitiveActionType, InputEvent
from bdlh_runtime.cognitive.goal_action_selector import GoalActionSelector
from bdlh_runtime.cognitive.orchestrator import CognitiveOrchestrator
from bdlh_runtime.cognitive.semantic_router import SemanticRouteSelector, build_kernel_router
from bdlh_runtime.domains.finance.cognitive_adapter import FinanceCognitiveSelector, InMemoryVerifiedEntityStore
from tests.helpers_encoder import LexicalEncoder
from tests.helpers_skill_catalog import DEMO_SKILL_CATALOG
from tests.helpers_understand import RuleBasedUnderstandModel


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
            handlers={"finance": FinanceCognitiveSelector(InMemoryVerifiedEntityStore(), knowledge_responder=respond)},
            catalog=DEMO_SKILL_CATALOG,
            respond=respond,
        ),
        fastpath=SemanticRouteSelector(
            build_kernel_router(encoder=LexicalEncoder()),
            knowledge_responder=respond,
        ),
        dispatcher=_NoDomain(),
        enabled_domains=frozenset({"finance"}),
        understand=RuleBasedUnderstandModel(),
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
            handlers={"finance": FinanceCognitiveSelector(InMemoryVerifiedEntityStore(), knowledge_responder=respond)},
            catalog=DEMO_SKILL_CATALOG,
            respond=respond,
        ),
        fastpath=SemanticRouteSelector(
            build_kernel_router(encoder=LexicalEncoder()),
            knowledge_responder=respond,
        ),
        dispatcher=_NoDomain(),
        enabled_domains=frozenset({"finance"}),
        understand=RuleBasedUnderstandModel(),
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
    assert result.response.audit_codes == ["RESPOND"]
    assert result.response.message.startswith("chat:")


@pytest.mark.asyncio
async def test_product_spine_skill_off_stock_talk_is_plain_chat() -> None:
    """没开工具时，Agent 直接回答，不会去澄清证券代码。"""
    respond = _Respond()
    app = CognitiveOrchestrator(
        selector=GoalActionSelector(
            handlers={"finance": FinanceCognitiveSelector(InMemoryVerifiedEntityStore(), knowledge_responder=respond)},
            catalog=DEMO_SKILL_CATALOG,
            respond=respond,
        ),
        fastpath=SemanticRouteSelector(
            build_kernel_router(encoder=LexicalEncoder()),
            knowledge_responder=respond,
        ),
        dispatcher=_NoDomain(),
        enabled_domains=frozenset({"finance"}),
        understand=RuleBasedUnderstandModel(),
    )
    result = await app.run(
        InputEvent(
            event_id="e1",
            user_id="u1",
            session_id="s1",
            message="600519今天怎么样",
            enabled_skills=frozenset(),
        ),
    )
    assert result.response.audit_codes == ["RESPOND"]
    assert result.response.message.startswith("chat:")
    assert result.response.response_kind == "ANSWER"
