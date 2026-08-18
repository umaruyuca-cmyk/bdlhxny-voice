"""进 Deep 之前的确定性调用策略（00 Prompt §6.5.1a）。

默认浅搜；满足任一项触发条件且硬约束通过 → 允许 ``research.deep_search``。
禁止在 ``web_search`` Adapter 内静默升档。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bdlh_runtime.tools.deep_research.contracts import DeepResearchRequest

# 用户明确要求深度研究（规则 1）
_EXPLICIT_DEEP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"深度调研",
        r"深入研究",
        r"深度研究",
        r"交叉验证",
        r"证据链",
        r"调研报告",
        r"研究报告",
        r"deep\s*research",
        r"cross[- ]?check",
        r"evidence\s*chain",
    )
)

# 比较 / 归因 / 趋势 / 风险机会 / 冲突观点（规则 4）
_COMPLEX_ANALYSIS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"比较|对比|对照",
        r"归因",
        r"趋势",
        r"风险|机会",
        r"冲突观点|分歧",
        r"\bcompar(e|ison)\b",
        r"\battribut",
        r"\btrend\b",
        r"\brisk\b|\bopportunit",
    )
)

_CRITERION_NOISE = re.compile(r"^[\s\-_*。．.、,，；;：:]+$")


@dataclass(frozen=True)
class DeepTriggerDecision:
    """调用策略输出；可审计。"""

    should_deep: bool
    reasons: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    deep_trigger_reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.should_deep and not self.deep_trigger_reasons:
            object.__setattr__(self, "deep_trigger_reasons", self.reasons)


def _nonempty_criteria(criteria: list[str]) -> list[str]:
    out: list[str] = []
    for item in criteria:
        text = (item or "").strip()
        if not text or _CRITERION_NOISE.match(text):
            continue
        if len(text) < 4:
            continue
        out.append(text)
    return out


def evaluate_deep_research_trigger(
    request: DeepResearchRequest,
    *,
    feature_enabled: bool = False,
    in_allowed: bool = False,
    entitled: bool = False,
    sync_budget_ok: bool = True,
    expected_independent_queries: int | None = None,
    user_text: str | None = None,
) -> DeepTriggerDecision:
    """在已拼好参数后判定是否应调用 Deep。

    Parameters
    ----------
    feature_enabled / in_allowed / entitled / sync_budget_ok
        硬约束；任一失败则 ``should_deep=False`` 并写入 ``blocked_reasons``。
    expected_independent_queries
        规则 5：预期独立检索问题数；``None`` 时不因本条触发（保守）。
    user_text
        可选用户原句/objective 拼接文本，用于规则 1/4 关键词；默认用
        ``question + objective``。
    """

    blocked: list[str] = []
    if not feature_enabled:
        blocked.append("feature_flag_off")
    if not in_allowed:
        blocked.append("not_in_allowed")
    if not entitled:
        blocked.append("not_entitled")
    if not sync_budget_ok:
        blocked.append("sync_budget_insufficient")

    text = (user_text or f"{request.question}\n{request.objective}").strip()
    reasons: list[str] = []

    if any(p.search(text) for p in _EXPLICIT_DEEP_PATTERNS):
        reasons.append("explicit_user_request")

    topics = [t.strip() for t in request.research_topics if (t or "").strip()]
    if len(topics) >= 2:
        reasons.append("research_topics_ge_2")

    criteria = _nonempty_criteria(list(request.success_criteria))
    if len(criteria) >= 2:
        reasons.append("success_criteria_ge_2")

    if any(p.search(text) for p in _COMPLEX_ANALYSIS_PATTERNS):
        reasons.append("complex_analysis_intent")

    if expected_independent_queries is not None and expected_independent_queries >= 3:
        reasons.append("expected_queries_ge_3")

    if blocked:
        return DeepTriggerDecision(
            should_deep=False,
            reasons=tuple(reasons),
            blocked_reasons=tuple(blocked),
            deep_trigger_reasons=(),
        )

    if not reasons:
        return DeepTriggerDecision(should_deep=False, reasons=(), blocked_reasons=())

    return DeepTriggerDecision(
        should_deep=True,
        reasons=tuple(reasons),
        blocked_reasons=(),
        deep_trigger_reasons=tuple(reasons),
    )
