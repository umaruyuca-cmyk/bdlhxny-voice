"""ContextBuilder：LangGraph 版每轮模型调用的上下文组装器。

架构文档 v3.1 §6 定义了 7 块上下文，其中 6 块确定性、仅 1 块（⑤ 召回记忆）
是语义的。这种设计让"黑箱可控"——每块都能单元测试，语义召回不准只影响
"是否贴合历史"，不影响计算正确性。

ContextBuilder 是纯函数式的：它不持有状态，只把传入的各来源数据组装成
结构化的 context dict，供 Query Agent / Summary Model 等结构化 LLM 节点
使用。它本身不调用任何外部服务（Mem0 的召回结果已由 load_memory 节点
写入 state，ContextBuilder 只是读取）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 7 块上下文的固定顺序，与架构文档 §6 一致
CONTEXT_BLOCKS = (
    "system_prompt",      # ① 固定系统提示
    "user_profile",       # ② 用户画像（确定性，来自 PG）
    "tool_manifest",      # ③ 工具清单（确定性，来自 ToolRegistry）
    "conversation",       # ④ 近期对话历史（确定性，带截断）
    "recalled_memories",  # ⑤ 召回的相关记忆（语义，来自 Mem0，带容差）
    "round_data",         # ⑥ 本轮已取数据（工具调用结果）
    "user_input",         # ⑦ 用户当前输入
)


@dataclass
class ContextBlock:
    """单块上下文的内容与来源标记。

    deterministic=True 表示该块来自确定性源（PG/Registry/Redis），
    False 表示语义源（Mem0 召回）。组装后的 context 会带上每块的
    确定性标记，便于调试和审计。
    """

    name: str
    content: Any
    deterministic: bool


@dataclass
class BuiltContext:
    """组装完成的完整上下文。"""

    blocks: dict[str, ContextBlock] = field(default_factory=dict)

    def to_prompt_dict(self) -> dict[str, Any]:
        """转为可直接喂给 LLM 的 dict（去掉确定性标记，只留内容）。"""
        return {name: block.content for name, block in self.blocks.items()}

    @property
    def deterministic_ratio(self) -> float:
        """确定性块占比，用于可观测性（应接近 6/7≈0.857）。"""
        if not self.blocks:
            return 0.0
        return sum(1 for b in self.blocks.values() if b.deterministic) / len(self.blocks)


# ── 固定的系统提示词（① 块）──
# 这是写死的，不随用户/请求变化。它定义了 Agent 的角色和硬约束。
_DEFAULT_SYSTEM_PROMPT = (
    "你是 StockWise 股票分析助手。你只能基于已提供的数据进行分析，"
    "不得编造行情、财务数据或结论。缺少数据时如实说明。"
    "技术指标和风险计算由确定性引擎完成，你负责理解、决策和表达。"
)


class ContextBuilder:
    """组装 7 块上下文的构建器。

    用法：在 Graph 节点中调用 build(state, ...) 得到 BuiltContext，
    再传给 LLM。Builder 不做 I/O，所有数据由调用方从 state/registry 传入。
    """

    def __init__(
        self,
        *,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        tool_manifest: list[dict[str, Any]] | None = None,
        max_conversation_turns: int = 10,
    ):
        """初始化构建器。

        system_prompt 和 tool_manifest 在 Graph 构建时确定（确定性），
        max_conversation_turns 控制对话历史的截断长度（防止 token 溢出）。
        """
        self._system_prompt = system_prompt
        self._tool_manifest = tool_manifest or []
        self._max_turns = max_conversation_turns

    def build(
        self,
        *,
        user_profile: dict[str, Any] | None,
        conversation: list[dict[str, Any]],
        recalled_memories: list[dict[str, Any]],
        round_data: list[dict[str, Any]] | None,
        user_input: dict[str, Any],
    ) -> BuiltContext:
        """组装完整上下文。

        所有参数来自 RootState（load_memory 节点写入的画像/记忆、
        conversation 累积的对话、本轮 observations 作为 round_data）。
        """
        ctx = BuiltContext()

        # ① 系统提示（固定，确定性）
        ctx.blocks["system_prompt"] = ContextBlock(
            name="system_prompt", content=self._system_prompt, deterministic=True
        )

        # ② 用户画像（来自 PG 结构化表，确定性）
        ctx.blocks["user_profile"] = ContextBlock(
            name="user_profile", content=user_profile or {}, deterministic=True
        )

        # ③ 工具清单（来自 ToolRegistry，确定性）
        ctx.blocks["tool_manifest"] = ContextBlock(
            name="tool_manifest", content=self._tool_manifest, deterministic=True
        )

        # ④ 近期对话历史（带截断，确定性）
        truncated = conversation[-self._max_turns :] if conversation else []
        ctx.blocks["conversation"] = ContextBlock(
            name="conversation", content=truncated, deterministic=True
        )

        # ⑤ 召回记忆（来自 Mem0，语义——唯一非确定性块，带容差）
        ctx.blocks["recalled_memories"] = ContextBlock(
            name="recalled_memories", content=recalled_memories or [], deterministic=False
        )

        # ⑥ 本轮已取数据（工具调用结果，确定性）
        ctx.blocks["round_data"] = ContextBlock(
            name="round_data", content=round_data or [], deterministic=True
        )

        # ⑦ 用户当前输入（HTTP 请求体，确定性）
        ctx.blocks["user_input"] = ContextBlock(
            name="user_input", content=user_input or {}, deterministic=True
        )

        return ctx
