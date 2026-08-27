"""对照组：LangGraph 官方预置 ReAct（create_react_agent）。

与裸 tool calling 基线同题库、同 LLM、同 canned executor、同系统提示词；唯一差异是
换成框架默认编排——ToolNode 统一执行（模型发起的非法工具名会被 ToolNode
拦截并回错误观察，而不是直接失败）、recursion_limit 控制步数。本组回答
「框架默认形态够不够」，与教程式手写循环基线互补。

langgraph 1.x 已把预置 agent 迁往 ``langchain.agents.create_agent``；当前
依赖未引入 langchain 包，使用 ``langgraph.prebuilt.create_react_agent``
（1.2.10 仍提供，升级到 2.0 前随依赖切换）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, ConfigDict, create_model

from tests.eval.baseline_agent import BaselineResult, _extract_text, _extract_tokens

REACT_RECURSION_LIMIT = 50

_JSON_TYPES: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _args_model(card: Any) -> type[BaseModel] | None:
    """把 ToolCard.parameters（JSON Schema）投影为 StructuredTool 的 args_schema。"""
    schema = card.parameters or {}
    props = schema.get("properties") or {}
    if not props:
        return None
    required = set(schema.get("required") or [])
    fields: dict[str, tuple[type, Any]] = {}
    for key, spec in props.items():
        py_type = _JSON_TYPES.get(str((spec or {}).get("type", "")), object)
        default = ... if key in required else None
        fields[key] = (py_type, default)
    return create_model(
        f"{card.name.replace('.', '_')}_args",
        __config__=ConfigDict(extra="allow"),
        **fields,
    )


def card_to_tool(card: Any, executor: Any) -> StructuredTool:
    """ToolCard → StructuredTool；执行闭包直连共用 executor（记录进 call_log）。"""
    name = str(card.name)

    async def _invoke(**kwargs: Any) -> dict[str, Any]:
        return await executor(name, kwargs)

    return StructuredTool.from_function(
        coroutine=_invoke,
        name=name,
        description=str(card.description),
        args_schema=_args_model(card),
    )


async def react_official_run(
    message: str,
    history: list[dict[str, str]],
    all_cards: list[Any],
    llm: Any,
    executor: Any,
    *,
    system_prompt: str,
    recursion_limit: int = REACT_RECURSION_LIMIT,
) -> BaselineResult:
    """Run LangGraph official create_react_agent with ALL tools and NO guardrails."""
    assistant_history = sum(1 for item in history if str(item.get("role")) == "assistant")
    messages: list[Any] = []
    for item in history:
        text = str(item.get("content", ""))
        if str(item.get("role", "user")) == "assistant":
            messages.append(AIMessage(content=text))
        else:
            messages.append(HumanMessage(content=text))
    messages.append(HumanMessage(content=message))

    try:
        tools = [card_to_tool(card, executor) for card in all_cards]
        agent = create_react_agent(llm, tools, prompt=system_prompt)
        out = await agent.ainvoke({"messages": messages}, config={"recursion_limit": recursion_limit})
    except GraphRecursionError:
        return BaselineResult(answer="（步数耗尽）", tool_calls=list(executor.call_log))
    except Exception as exc:  # noqa: BLE001 — 与裸调用组同口径，异常降级为结果而非中断
        return BaselineResult(answer=f"（执行失败：{exc}）", error=str(exc), tool_calls=list(executor.call_log))

    msgs = list(out.get("messages", []))
    ai_messages = [m for m in msgs if isinstance(m, AIMessage)]
    answer = _extract_text(msgs[-1]) if msgs else ""
    if "need more steps" in answer:
        # langgraph 1.x 步数耗尽时不抛 GraphRecursionError，而是追加固定道歉消息收尾；
        # 归一为与裸调用组「轮次耗尽」同位的中文口径。
        answer = "（步数耗尽）"
    prompt_tokens = 0
    completion_tokens = 0
    for m in ai_messages:
        p, c = _extract_tokens(m)
        prompt_tokens += p
        completion_tokens += c
    return BaselineResult(
        answer=answer,
        tool_calls=list(executor.call_log),
        rounds=max(0, len(ai_messages) - assistant_history),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        attempted_tools=[str(call.get("name")) for m in ai_messages for call in (m.tool_calls or [])],
    )
