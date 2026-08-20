"""GoalCoverage：确定性覆盖判定控制器（重写 §4）。

无 LLM。三分支判定：
1. ``needs_account / needs_profile`` 标记真 → 账户/画像 Goal 专用判定
   （全部无证 BLOCKED；有证须 portfolio.*/user.* Observation，市场行情不能顶）；
2. 有 topic → 主题能力 OR 覆盖（一条成功即 COVERED，provider 挂一条不 BLOCKED）；
3. 无 topic 未标记 → 需要至少一条非纯 resolve 的业务数据 Observation。

规则降级兜底（「任一非空 Observation 即 COVERED」）只属于无 LLM 降级路径，
由 ``rule_based_fallback=True`` 显式启用，正式判定不得引用。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.registry import RegistrySnapshot, dependency_closure

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


def backfill_criteria(
    snapshot: RegistrySnapshot,
    goals: list[GoalSpec],
    allowed: list[str],
) -> list[GoalSpec]:
    """控制器回填：按 topic 对照表 + depends_on 闭包计算 candidate_capabilities。

    闭包能力（如 resolve）单独记录、不进 OR 集合——只要求先于主题能力 SUCCESS。
    """
    allowed_set = set(allowed)
    updated: list[GoalSpec] = []
    for goal in goals:
        criteria = []
        for criterion in goal.success_criteria:
            if criterion.topic is not None:
                topic_caps = [name for name in snapshot.topic_capabilities_for(criterion.topic) if name in allowed_set]
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
    snapshot: RegistrySnapshot,
    *,
    rule_based_fallback: bool = False,
) -> list[GoalSpec]:
    """对每个 Goal 做覆盖判定并回填 observation_refs / status。"""
    allowed_set = set(allowed)
    usable = _usable_observations(observations)
    updated: list[GoalSpec] = []
    for goal in goals:
        status, refs = _evaluate_one(goal, usable, allowed_set, snapshot, rule_based_fallback)
        updated.append(goal.model_copy(update={"status": status, "observation_refs": refs}))
    return updated


def _evaluate_one(
    goal: GoalSpec,
    usable: dict[str, list[str]],
    allowed_set: set[str],
    snapshot: RegistrySnapshot,
    rule_based_fallback: bool,
) -> tuple[str, list[str]]:
    # ── 分支 1：账户 / 画像 Goal（RequestedTopic 无此主题，靠标记判定）──
    if goal.needs_account or goal.needs_profile:
        prefix = _ACCOUNT_PREFIX if goal.needs_account else _PROFILE_PREFIX
        owned = {name for name in allowed_set if name.startswith(prefix)}
        if not owned:
            return "BLOCKED", []
        refs: list[str] = []
        for name in owned:
            refs.extend(usable.get(name, []))
        return ("COVERED", sorted(set(refs))) if refs else ("PENDING", [])

    # ── 分支 2/3：按 criterion 判定 ──
    all_refs: list[str] = []
    any_blocked = False
    for criterion in goal.success_criteria:
        if criterion.topic is not None:
            # 分支 2：主题能力 OR 覆盖
            candidates = criterion.candidate_capabilities
            if not candidates:
                # 主题能力全部不在 allowed → 资格缺口
                topic_caps = snapshot.topic_capabilities_for(criterion.topic)
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
            # 分支 3：无 topic → 需要非纯 resolve 的业务数据 Observation
            business = [name for name in usable if name not in RESOLVE_CAPABILITIES]
            if business:
                for name in business:
                    all_refs.extend(usable[name])
            elif rule_based_fallback and usable:
                # 规则降级专用兜底：仅无 LLM 环境启用；正式判定不得引用
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


def dependency_names(snapshot: RegistrySnapshot, names: list[str]) -> list[str]:
    """闭包能力名单（不进 OR 集合，仅顺序约束）。"""
    return dependency_closure(snapshot, names)
