"""执行模式选择契约（v2.1 §3）。

执行模式选择不是固定业务工作流分类。它只决定本轮采用直接回答、单能力查询
还是受控 Agent Loop；不决定复杂研究的具体工具、分析步骤或最终结论。

降级规则（v2.1 §3.3）：
- direct_response 仅适用不依赖实时金融事实的知识解释；
- single_capability 的工具建议仍须经实体解析、参数校验和 Guardrails；
- LLM 不可用、解析失败、置信度低或歧义时默认进入 agent_loop；
- 快路径发现数据不足时升级到 agent_loop；
- 拿不准时偏向 agent_loop。

名称解析边界（v2.1 §3.4，定稿方案 B）：
- 用户给 symbol → single_capability 直接调能力；
- 用户给名称 → agent_loop（planner 先 resolve_instrument 再调能力）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolProposal(BaseModel):
    """single_capability 模式的工具建议（仍须经 Guardrails 校验）。"""

    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class IntentRoute(BaseModel):
    """执行模式选择输出。

    - direct_response: 不依赖实时金融事实的知识解释，可带预览回答；
    - single_capability: 一次统一能力调用（标的已解析为 symbol）；
    - agent_loop: 复杂研究 / 多实体 / 名称需解析，走 planner-executor。
    """

    mode: Literal["direct_response", "single_capability", "agent_loop"]
    reason: str
    confidence: float | None = None
    direct_answer: str | None = None
    tool_proposal: ToolProposal | None = None
