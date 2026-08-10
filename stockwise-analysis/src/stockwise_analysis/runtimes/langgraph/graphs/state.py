"""Root Graph 的统一状态定义。

State 是短期运行记忆：它随 Checkpointer 保存并可由同一 ``thread_id`` 恢复。
长期用户偏好和语义记忆通过 Mem0 在对话首尾召回/沉淀，不常驻 State——
但召回结果需注入 ContextBuilder，因此用专门字段短暂持有（见 §5.1）。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class RootState(TypedDict, total=False):
    """根流程和子图共享的、可持久化的运行状态。"""

    run_id: str
    thread_id: str
    user_id: str | None
    request: dict[str, Any]
    # 列表字段采用 reducer 追加，避免子图更新时覆盖先前的轨迹。
    conversation: Annotated[list[dict[str, Any]], operator.add]
    intent: dict[str, Any]
    needs_clarification: bool
    clarification_request: dict[str, Any] | None
    workflow_plan: dict[str, Any]
    current_task_id: str | None
    next_stage: str | None
    data_requirements: list[dict[str, Any]]
    # 所有外部结果必须先标准化为 Observation，再进入分析输入。
    observations: Annotated[list[dict[str, Any]], operator.add]
    analysis_input: dict[str, Any] | None
    analysis_result: dict[str, Any] | None
    final_response: dict[str, Any] | None
    confirmation_required: bool
    confirmation: dict[str, Any] | None
    status: str
    errors: Annotated[list[dict[str, Any]], operator.add]
    # ── 记忆层字段（仅对话首尾读写，ReAct 循环不碰）──
    # load_memory 节点写入，供 ContextBuilder 第 ②⑤ 块注入。
    user_profile: dict[str, Any] | None
    recalled_memories: list[dict[str, Any]]
    # Event 用于 SSE、审计和调试，不能记录密钥或未脱敏敏感字段。
    events: Annotated[list[dict[str, Any]], operator.add]
