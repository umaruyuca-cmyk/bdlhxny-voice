"""GoalCoverage：确定性覆盖判定控制器。

无 LLM。三分支判定：
1. ``needs_account / needs_profile`` 标记真 → 账户/画像 Goal 专用判定；
2. 有 topic → 主题能力 OR 覆盖；
3. 无 topic 未标记 → 需要至少一条非纯 resolve 的业务数据 Observation。

规则降级兜底由 ``rule_based_fallback=True`` 显式启用，正式判定不得引用。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.cognitive.topic_hints import topic_capabilities_for

from .goal_schema import GoalSpec

#: 纯前置解析能力：不构成业务数据覆盖
RESOLVE_CAPABILITIES = {"market.resolve_instrument"}

_ACCOUNT_PREFIX = "portfolio."
_PROFILE_PREFIX = "user."


def _usable_observations(observations: list[dict[str, Any]]) -> dict[str, list[str]]:
    """capability → 可用 observation id 列表（SUCCESS，或 PARTIAL 且 data 非空）。"""
    usable: dict[str, list[str]] = {}
    for obs in observations:
        capability = str(obs.get("capability") or "")
        status = obs.get("status")
        data = obs.get("data")
        ok = status == "SUCCESS" or (status == "PARTIAL" and data not in (None, {}, []))
        if capability and ok:
            usable.setdefault(capability, []).append(str(obs.get("observation_id") or ""))
    return usable


def backfill_criteria(goals: list[GoalSpec], allowed: list[str]) -> list[GoalSpec]:
    """控制器回填：按主题覆盖提示计算 candidate_capabilities（只在 allowed 内取交）。"""
    allowed_set = set(allowed)
    updated: list[GoalSpec] = []
    for goal in goals:
        criteria = []
        for criterion in goal.success_criteria:
            if criterion.topic is not None:
                topic_caps = [name for name in topic_capabilities_for(criterion.topic) if name in allowed_set]
                candidate = sorted(topic_caps)
            elif goal.needs_account:
                candidate = sorted(name for name in allowed_set if name.startswith(_ACCOUNT_PREFIX))
            elif goal.needs_profile:
                candidate = sorted(name for name in allowed_set if name.startswith(_PROFILE_PREFIX))
            else:
                candidate = []
            criteria.append(criterion.model_copy(update={"candidate_capabilities": candidate}))
        updated.append(goal.model_copy(update={"success_criteria": criteria}))
    return updated


def evaluate_goals(
    goals: list[GoalSpec],
    observations: list[dict[str, Any]],
    allowed: list[str],
    *,
    rule_based_fallback: bool = False,
) -> list[GoalSpec]:
    """对每个 Goal 做覆盖判定并回填 observation_refs / status。"""
    allowed_set = set(allowed)
    usable = _usable_observations(observations)
    updated: list[GoalSpec] = []
    for goal in goals:
        status, refs = _evaluate_one(goal, usable, allowed_set, rule_based_fallback)
        updated.append(goal.model_copy(update={"status": status, "observation_refs": refs}))
    return updated


def _evaluate_one(
    goal: GoalSpec,
    usable: dict[str, list[str]],
    allowed_set: set[str],
    rule_based_fallback: bool,
) -> tuple[str, list[str]]:
    if goal.needs_account or goal.needs_profile:
        prefix = _ACCOUNT_PREFIX if goal.needs_account else _PROFILE_PREFIX
        owned = {name for name in allowed_set if name.startswith(prefix)}
        if not owned:
            return "BLOCKED", []
        refs: list[str] = []
        for name in owned:
            refs.extend(usable.get(name, []))
        return ("COVERED", sorted(set(refs))) if refs else ("PENDING", [])

    all_refs: list[str] = []
    any_blocked = False
    for criterion in goal.success_criteria:
        if criterion.topic is not None:
            candidates = criterion.candidate_capabilities
            if not candidates:
                topic_caps = topic_capabilities_for(criterion.topic)
                if topic_caps and not (set(topic_caps) & allowed_set):
                    any_blocked = True
                    continue
                any_blocked = True
                continue
            covered_refs: list[str] = []
            for name in candidates:
                covered_refs.extend(usable.get(name, []))
            if not covered_refs:
                return "PENDING", []
            all_refs.extend(covered_refs)
        else:
            business = [name for name in usable if name not in RESOLVE_CAPABILITIES]
            if business:
                for name in business:
                    all_refs.extend(usable[name])
            elif rule_based_fallback and usable:
                for name in usable:
                    all_refs.extend(usable[name])
            else:
                return "PENDING", []
    if any_blocked:
        return "BLOCKED", sorted(set(all_refs))
    return "COVERED", sorted(set(all_refs))


def all_goals_settled(goals: list[GoalSpec]) -> bool:
    """FINISH 建议被接受的前置：所有 Goal ∈ {COVERED, BLOCKED}。"""
    return all(goal.status in {"COVERED", "BLOCKED"} for goal in goals)
