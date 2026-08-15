"""ContextBuilder 单元测试，验证 7 块上下文组装和确定性比例。"""

from __future__ import annotations

import pytest

from bdlh_runtime.memory.base import MemoryRecord, UserProfile
from bdlh_runtime.runtimes.langgraph.context import ContextBuilder, ContextService


def test_builds_all_seven_blocks():
    """组装后的 context 必须包含全部 7 块。"""
    builder = ContextBuilder(tool_manifest=[{"name": "market.get_realtime_quote"}])
    ctx = builder.build(
        user_profile={"risk_tolerance": "moderate"},
        conversation=[{"role": "user", "content": "茅台怎么样"}],
        recalled_memories=[{"content": "用户偏好白酒板块"}],
        round_data=[{"capability": "market.get_realtime_quote"}],
        user_input={"message": "分析 600519"},
    )
    assert set(ctx.blocks.keys()) == {
        "system_prompt", "user_profile", "tool_manifest",
        "conversation", "recalled_memories", "round_data", "user_input",
    }


def test_deterministic_ratio_is_six_sevenths():
    """7 块中 6 块确定性，仅 recalled_memories 是语义——比例应 ≈0.857。"""
    builder = ContextBuilder()
    ctx = builder.build(
        user_profile=None,
        conversation=[],
        recalled_memories=[],
        round_data=None,
        user_input={},
    )
    assert abs(ctx.deterministic_ratio - 6 / 7) < 0.001


def test_recalled_memories_is_only_non_deterministic():
    """只有 recalled_memories 块的 deterministic=False。"""
    builder = ContextBuilder()
    ctx = builder.build(
        user_profile={"x": 1},
        conversation=[{"a": 1}],
        recalled_memories=[{"content": "test"}],
        round_data=[],
        user_input={"msg": "hi"},
    )
    non_det = [name for name, block in ctx.blocks.items() if not block.deterministic]
    assert non_det == ["recalled_memories"]


def test_conversation_truncated():
    """对话历史超出 max_turns 时应截断。"""
    builder = ContextBuilder(max_conversation_turns=3)
    long_conversation = [{"role": "user", "content": str(i)} for i in range(10)]
    ctx = builder.build(
        user_profile=None,
        conversation=long_conversation,
        recalled_memories=[],
        round_data=None,
        user_input={},
    )
    assert len(ctx.blocks["conversation"].content) == 3
    # 截断的是最新的 3 条
    assert ctx.blocks["conversation"].content[-1]["content"] == "9"


def test_to_prompt_dict_strips_metadata():
    """to_prompt_dict 只保留内容，去掉确定性标记。"""
    builder = ContextBuilder()
    ctx = builder.build(
        user_profile={"risk": "high"},
        conversation=[],
        recalled_memories=[],
        round_data=None,
        user_input={"message": "test"},
    )
    prompt = ctx.to_prompt_dict()
    assert "system_prompt" in prompt
    assert "deterministic" not in str(prompt["user_profile"])


def test_budget_keeps_user_input_and_records_dropped_blocks():
    builder = ContextBuilder(max_conversation_turns=10)
    ctx = builder.build(
        user_profile=None,
        conversation=[{"role": "user", "content": "旧消息" * 200}],
        recalled_memories=[{"content": "语义记忆" * 200}],
        round_data=[{"payload": "工具数据" * 200}],
        user_input={"message": "当前输入不得丢失"},
        purpose="classify",
        budget=120,
    )
    assert ctx.purpose == "classify"
    assert ctx.token_budget == 120
    assert ctx.blocks["user_input"].content == {"message": "当前输入不得丢失"}
    assert ctx.dropped


class _MemoryStore:
    def __init__(self) -> None:
        self.search_calls = 0

    async def get_profile(self, _user_id: str) -> UserProfile:
        return UserProfile(user_id="user-1", risk_tolerance="moderate")

    async def search(self, _query: str, _user_id: str, *, limit: int = 5) -> list[MemoryRecord]:
        self.search_calls += 1
        assert limit == 5
        return [MemoryRecord(content="偏好长期持有", score=0.9)]


@pytest.mark.asyncio
async def test_context_service_is_the_mem0_read_boundary():
    store = _MemoryStore()
    service = ContextService(builder=ContextBuilder(), memory_store=store)
    context = await service.build(
        user_id="user-1",
        conversation=[],
        round_data=[],
        user_input={"message": "分析茅台"},
        purpose="answer",
    )
    assert store.search_calls == 1
    assert context.blocks["user_profile"].content["risk_tolerance"] == "moderate"
    assert context.blocks["recalled_memories"].content[0]["content"] == "偏好长期持有"


@pytest.mark.asyncio
async def test_context_service_skips_mem0_for_route_confirmation():
    store = _MemoryStore()
    service = ContextService(builder=ContextBuilder(), memory_store=store)
    context = await service.build(
        user_id="user-1",
        conversation=[],
        round_data=[],
        user_input={"message": "继续吗"},
        purpose="confirm_route",
        budget="small",
    )
    assert store.search_calls == 0
    assert context.blocks["recalled_memories"].content == []
