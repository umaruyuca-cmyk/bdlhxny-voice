"""Baseline: 裸 LLM tool calling，不含任何 Agent 工程模式。

这是大多数人跟着 LangChain 教程写出来的东西：
- 全部工具装入上下文（无 Selective Loading）
- 无治理中间件（无 G1-G7）
- 无语义快路径（每条消息都进循环）
- 无 Output Guardrail（LLM 原样返回）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


@dataclass
class BaselineResult:
    answer: str
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    rounds: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # API 未回 usage、token 为 chars//4 近似时置 True，指标口径可区分。
    tokens_estimated: bool = False
    error: str | None = None
    # LangGraph 官方 ReAct 对照组专用：模型实际发起的 tool_calls 名单。
    # ToolNode 会拦截非法工具名（不执行），只有这份名单能完整记录幻觉尝试；
    # 裸调用组无门禁，attempted == executed，保持为空即可。
    attempted_tools: list[str] = field(default_factory=list)


def _tool_spec(card: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": card.name,
            "description": card.description,
            "parameters": card.parameters,
        },
    }


def _extract_tool_calls(response: Any) -> list[tuple[str, str, dict[str, Any]]]:
    raw = getattr(response, "tool_calls", None) or []
    parsed: list[tuple[str, str, dict[str, Any]]] = []
    for call in raw:
        if isinstance(call, dict):
            name = str(call.get("name") or "")
            call_id = str(call.get("id") or "")
            args: Any = call.get("args") or call.get("arguments") or {}
        else:
            name = str(getattr(call, "name", "") or "")
            call_id = str(getattr(call, "id", "") or "")
            args = getattr(call, "args", {}) or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        if name:
            parsed.append((call_id, name, args))
    return parsed


def _extract_text(response: Any) -> str:
    content = getattr(response, "content", "") or ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _extract_tokens(response: Any) -> tuple[int, int, bool]:
    """提取 (prompt, completion, 是否近似估算)。

    API 不回 usage 时按文本长度近似（chars//4）并置估算标记；
    真实值与近似值不混用同一口径。
    """
    # langchain 0.2+: usage_metadata typed object
    um = getattr(response, "usage_metadata", None)
    if um is not None:
        p = int(getattr(um, "input_tokens", 0) or 0)
        c = int(getattr(um, "output_tokens", 0) or 0)
        if p > 0 or c > 0:
            return p, c, False
    # response_metadata.token_usage (OpenAI format)
    meta = getattr(response, "response_metadata", None)
    if isinstance(meta, dict):
        usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(usage, dict) and usage:
            p = int(usage.get("prompt_tokens", 0) or 0)
            c = int(usage.get("completion_tokens", 0) or 0)
            if p > 0 or c > 0:
                return p, c, False
    # Fallback: estimate from response text (rough, but captures relative diff)
    text = _extract_text(response)
    approx = max(1, len(text) // 4)
    return 0, approx, True


#: 基线系统提示词（单一真源：裸调用与 ReAct 对照共用，ab_eval 复用）
BASELINE_SYSTEM = (
    "你是工具型助手。请根据用户问题调用合适的工具获取数据，然后给出分析回答。"
    "不得编造未由工具提供的数据。"
)


async def naive_run(
    message: str,
    history: list[dict[str, str]],
    all_cards: list[Any],
    llm: Any,
    executor: Any,
    *,
    system_prompt: str = BASELINE_SYSTEM,
    max_rounds: int = 10,
) -> BaselineResult:
    """Run a naive LLM tool-calling loop with ALL tools and NO guardrails."""
    specs = [_tool_spec(c) for c in all_cards]
    bound = llm.bind_tools(specs)

    messages: list[Any] = [SystemMessage(content=system_prompt)]
    for item in history:
        role = str(item.get("role", "user"))
        text = str(item.get("content", ""))
        if role == "assistant":
            messages.append(AIMessage(content=text))
        else:
            messages.append(HumanMessage(content=text))
    messages.append(HumanMessage(content=message))

    tool_log: list[tuple[str, dict[str, Any]]] = []
    total_prompt = 0
    total_completion = 0
    rounds = 0
    tokens_estimated = False

    try:
        for _ in range(max_rounds):
            rounds += 1
            response = await bound.ainvoke(messages)
            messages.append(response)
            p, c, estimated = _extract_tokens(response)
            total_prompt += p
            total_completion += c
            tokens_estimated = tokens_estimated or estimated

            calls = _extract_tool_calls(response)
            if not calls:
                return BaselineResult(
                    answer=_extract_text(response),
                    tool_calls=tool_log,
                    rounds=rounds,
                    prompt_tokens=total_prompt,
                    completion_tokens=total_completion,
                    tokens_estimated=tokens_estimated,
                )
            for call_id, name, args in calls:
                result = await executor(name, args)
                tool_log.append((name, dict(args)))
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False, default=str),
                        tool_call_id=call_id or name,
                    )
                )
    except Exception as exc:
        return BaselineResult(
            answer=f"（执行失败：{exc}）",
            tool_calls=tool_log,
            rounds=rounds,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            tokens_estimated=tokens_estimated,
            error=str(exc),
        )

    return BaselineResult(
        answer="（轮次耗尽）",
        tool_calls=tool_log,
        rounds=rounds,
        prompt_tokens=total_prompt,
        completion_tokens=total_completion,
        tokens_estimated=tokens_estimated,
    )
