"""Cognitive 侧 Deep Research 调用辅助（ADR-016 M4 轻量接线）。

- 从 RootState 拼 ``DeepResearchRequest`` 参数
- 选中 deep 后若调用策略未触发 → 降级 ``research.web_search``（若在 allowed）
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from bdlh_runtime.tools.deep_research import (
    DEEP_SEARCH_CAPABILITY,
    DeepResearchRequest,
    WEB_SEARCH_CAPABILITY,
    evaluate_deep_research_trigger,
)


def user_text_from_state(state: dict[str, Any]) -> str:
    request = state.get("request") or {}
    for key in ("text", "message", "query", "user_text"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    understand = state.get("understand") or {}
    for key in ("raw_text", "normalized_text"):
        value = understand.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_deep_research_arguments(state: dict[str, Any], *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """为 ``research.deep_search`` 补齐契约字段；不把入口 ``requested_topics`` 自动当 research_topics。"""

    arguments = dict(base or {})
    text = user_text_from_state(state)
    run_id = str(state.get("run_id") or "").strip() or str(uuid4())
    arguments.setdefault("request_id", run_id)
    if not str(arguments.get("question") or "").strip():
        arguments["question"] = text or "研究请求"
    if not str(arguments.get("objective") or "").strip():
        arguments["objective"] = "收集可引用的公开研究资料以支持后续分析"
    # research_topics 仅在调用方已显式传入时保留；禁止从 Goal.requested_topics 偷渡升级
    if "research_topics" not in arguments:
        arguments["research_topics"] = []
    if "success_criteria" not in arguments:
        arguments["success_criteria"] = []
    return arguments


def apply_deep_call_policy_to_action(
    action: dict[str, Any],
    state: dict[str, Any],
    *,
    allowed: set[str],
) -> dict[str, Any]:
    """若动作是 deep_search 但策略未触发，降级浅搜或 finish。"""

    if action.get("action") != DEEP_SEARCH_CAPABILITY:
        return action
    if DEEP_SEARCH_CAPABILITY not in allowed:
        return {
            "action": "finish",
            "arguments": {},
            "reason": "research.deep_search not in allowed",
        }

    args = build_deep_research_arguments(state, base=action.get("arguments") or {})
    try:
        request = DeepResearchRequest.model_validate(args)
    except Exception:  # noqa: BLE001
        request = DeepResearchRequest(
            request_id=str(args.get("request_id") or uuid4()),
            question=str(args.get("question") or "research"),
            objective=str(args.get("objective") or "research"),
        )

    # deep 已在 allowed ⇒ Feature Flag / 资格已过；此处只跑触发规则
    decision = evaluate_deep_research_trigger(
        request,
        feature_enabled=True,
        in_allowed=True,
        entitled=True,
        sync_budget_ok=True,
        user_text=user_text_from_state(state) or None,
        expected_independent_queries=(
            max(len(request.research_topics), len(request.success_criteria), 1)
        ),
    )
    if decision.should_deep:
        return {
            **action,
            "arguments": args,
            "reason": action.get("reason")
            or f"deep_trigger:{','.join(decision.deep_trigger_reasons)}",
            "deep_trigger_reasons": list(decision.deep_trigger_reasons),
        }

    if WEB_SEARCH_CAPABILITY in allowed:
        query = user_text_from_state(state) or request.question
        return {
            "action": WEB_SEARCH_CAPABILITY,
            "arguments": {"query": query},
            "reason": (
                "deep_call_policy_blocked:"
                + (",".join(decision.reasons) or "no_trigger")
                + ";downgrade_web_search"
            ),
        }
    return {
        "action": "finish",
        "arguments": {},
        "reason": "deep_call_policy_blocked_no_web_fallback",
    }
