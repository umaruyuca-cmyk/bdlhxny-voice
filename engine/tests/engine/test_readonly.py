"""只读拦截：目录拒绝危险动作工具；循环内幻觉危险名被治理中间件挡住。"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.engine.contracts import InputEvent
from bdlh_runtime.engine.loop import AgentLoop
from bdlh_runtime.engine.runtime import EngineRuntime
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog, ToolOrigin, is_trading_semantic
from tests.engine.test_loop import FakeChatModel


def test_catalog_rejects_trading_and_non_readonly(finance_pack) -> None:
    catalog = ToolCatalog()
    assert is_trading_semantic("order.place_order", "place a buy order")
    with pytest.raises(ValueError, match="危险动作"):
        catalog.register(
            ToolCard(
                name="order.place_order",
                description="place a buy order",
                parameters={"type": "object", "properties": {}},
                origin=ToolOrigin.LOCAL,
                read_only=True,
            )
        )
    with pytest.raises(ValueError, match="只读红线"):
        catalog.register(
            ToolCard(
                name="memory.write",
                description="写入记忆",
                parameters={"type": "object", "properties": {}},
                origin=ToolOrigin.LOCAL,
                read_only=False,
            )
        )


def test_catalog_allows_trading_wording_when_profile_empty() -> None:
    from bdlh_runtime.scenarios import disable_all_scenario_packs
    from bdlh_runtime.scenarios.dangerous_actions import clear_profiles

    disable_all_scenario_packs()
    clear_profiles()
    catalog = ToolCatalog()
    catalog.register(
        ToolCard(
            name="order.place_order",
            description="place a buy order",
            parameters={"type": "object", "properties": {}},
            origin=ToolOrigin.LOCAL,
            read_only=True,
        )
    )
    assert catalog.contains("order.place_order")


@pytest.mark.asyncio
async def test_hallucinated_trading_tool_is_blocked() -> None:
    catalog = ToolCatalog()
    catalog.register(
        ToolCard(
            name="weather.get_forecast",
            description="查询天气预报",
            parameters={"type": "object", "properties": {"city": {"type": "string"}}},
            origin=ToolOrigin.LOCAL,
            read_only=True,
            required_scope=["general_read"],
        )
    )
    llm = FakeChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "order.place_order",
                        "args": {"symbol": "300750"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="不该执行未装载工具"),
        ]
    )
    runtime = EngineRuntime(
        AgentLoop(
            llm=llm,
            catalog=catalog,
            executor=lambda name, arguments: {"tool": name, "args": arguments},
        )
    )
    execution = await runtime.run(
        InputEvent(
            event_id="e1",
            user_id="user-1",
            session_id="s1",
            run_id="r-readonly",
            message="帮我执行一个未装载的写操作",
        )
    )
    assert execution.response.response_kind == "BLOCKED"
    assert "TOOL_NOT_VISIBLE" in execution.response.audit_codes
    assert "guardrail.blocked" in execution.state.public_events
