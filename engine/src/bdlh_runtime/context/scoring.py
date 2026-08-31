"""公式五(重要度评分)与公式六(性价比选择值)的确定性实现。

对应《重要度评分与性价比选择公式设计.md》;全部因子只用条目自带元数据,
不调用外部模型、不学习参数,同一输入同一输出。

启用方式(v2,可选):``ContextBuilder(scorer=MultiFactorScorer(...))``;
不传 scorer 时 budgeted 保持 v1(直接 priority + 公平份额)行为,便于
budgeted-v1 与 v2 的受控对照。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .models import ContextItem, ContextRole, ItemScore

SCORING_VERSION = "multi-factor-v2"

#: 各因子半衰期(小时);0 表示不衰减(恒 1.0)
_HALF_LIFE_HOURS: dict[str, float] = {
    "market_observation": 5 / 60,
    "news_evidence": 24.0,
    "portfolio_fact": 24 * 7,
    "fundamental_observation": 24 * 90,
    "tool_result": 24 * 7,
    "tool_failure": 24 * 7,
    "user_profile": 0.0,
    "system_constraint": 0.0,
    "memory_fact": 0.0,
}
_DEFAULT_HALF_LIFE_HOURS = 0.0  # 未知类型不衰减,交由 staleness 处理新旧

#: authority 默认表(None 时按 role/item_type 推导,设计稿 §2.2)
_AUTHORITY_BY_ROLE: dict[str, float] = {
    ContextRole.SYSTEM.value: 1.0,
    ContextRole.INSTRUCTION.value: 1.0,
}
_AUTHORITY_BY_TYPE: dict[str, float] = {
    "system_constraint": 1.0,
    "case_input": 1.0,
    "market_observation": 0.9,
    "portfolio_fact": 0.9,
    "fundamental_observation": 0.9,
    "tool_result": 0.9,
    "memory_fact": 0.7,
    "assistant_conclusion": 0.5,
    "news_evidence": 0.2,
    "web_text": 0.2,
    "log": 0.2,
}
_AUTHORITY_DEFAULT = 0.7  # 用户确认的约束/普通条目


@dataclass(frozen=True)
class ScoringWeights:
    """公式五权重(场景配置;ws 为减法项单独上限 0.3)。"""

    wr: float
    wa: float
    wf: float
    wq: float
    wi: float
    wc: float
    we: float
    ws: float
    scene: str = "default"
    version: str = SCORING_VERSION

    def validate(self) -> None:
        names = ("wr", "wa", "wf", "wq", "wi", "wc", "we")
        for name in names + ("ws",):
            if getattr(self, name) < 0:
                raise ValueError(f"scoring weight {name} must be non-negative")
        total = sum(getattr(self, name) for name in names)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"scoring weights must sum to 1 (got {total:.4f});拒绝静默归一化")
        if self.ws > 0.3:
            raise ValueError("staleness weight ws must be <= 0.3 (subtraction term)")
        if max(getattr(self, name) for name in names) < 0.20:
            raise ValueError("at least one weight must be >= 0.20")


#: 设计稿 §2.3 场景权重表(第一版手工常量,后续用对照评测校准)。
#: 注:设计稿表格中「看护/知识」两列与「合计 1.00」自相矛盾(原列合计
#: 1.10/0.85);此处按校验约束修正为合计 1.00,偏离方向:看护 wq 0.15→0.05,
#: 知识 wa 0.15→0.30(权威度是知识场景核心),default wf 0.05→0.10。
SCENE_WEIGHTS: dict[str, ScoringWeights] = {
    "market": ScoringWeights(0.25, 0.15, 0.30, 0.10, 0.10, 0.05, 0.05, 0.10, scene="market"),
    "research": ScoringWeights(0.25, 0.20, 0.05, 0.15, 0.20, 0.10, 0.05, 0.10, scene="research"),
    "portfolio": ScoringWeights(0.20, 0.15, 0.10, 0.15, 0.20, 0.10, 0.10, 0.10, scene="portfolio"),
    "suitability": ScoringWeights(0.20, 0.25, 0.05, 0.15, 0.20, 0.10, 0.05, 0.10, scene="suitability"),
    "watch": ScoringWeights(0.25, 0.15, 0.20, 0.05, 0.10, 0.10, 0.15, 0.10, scene="watch"),
    "intercept": ScoringWeights(0.15, 0.25, 0.05, 0.10, 0.30, 0.05, 0.10, 0.10, scene="intercept"),
    "knowledge": ScoringWeights(0.30, 0.30, 0.05, 0.10, 0.10, 0.10, 0.05, 0.10, scene="knowledge"),
}
DEFAULT_WEIGHTS = ScoringWeights(0.25, 0.20, 0.10, 0.15, 0.15, 0.10, 0.05, 0.10, scene="default")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass
class ScoringContext:
    """一次构建的评分上下文(引用计数与取代关系由调用方预处理)。"""

    reference_time: datetime | None = None
    #: 场景"优先保留"清单(task_impact=0.5)与"通常省略"清单(0.2)
    preferred_ids: frozenset[str] = field(default_factory=frozenset)
    omit_ids: frozenset[str] = field(default_factory=frozenset)


class MultiFactorScorer:
    """公式五/六的确定性评分器;只读元数据,无副作用。"""

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        *,
        scene: str = "default",
        context: ScoringContext | None = None,
    ) -> None:
        if weights is None:
            weights = SCENE_WEIGHTS.get(scene, DEFAULT_WEIGHTS)
        weights.validate()
        self.weights = weights
        self.context = context or ScoringContext()

    # ── 公式五 ────────────────────────────────────────────────────────────

    def priority(self, item: ContextItem) -> tuple[float, dict[str, float]]:
        factors = {
            "relevance": self._relevance(item),
            "authority": self._authority(item),
            "freshness": self._freshness(item),
            "source_quality": self._source_quality(item),
            "task_impact": self._task_impact(item),
            "citation_dependency": self._citation_dependency(item),
            "failure_risk": self._failure_risk(item),
            "staleness": self._staleness(item),
        }
        w = self.weights
        raw = (
            w.wr * factors["relevance"]
            + w.wa * factors["authority"]
            + w.wf * factors["freshness"]
            + w.wq * factors["source_quality"]
            + w.wi * factors["task_impact"]
            + w.wc * factors["citation_dependency"]
            + w.we * factors["failure_risk"]
            - w.ws * factors["staleness"]
        )
        return min(1.0, max(0.0, raw)), factors

    # ── 公式六 ────────────────────────────────────────────────────────────

    def selection_value(self, priority: float, representation_tokens: int) -> float:
        if representation_tokens <= 0:
            return 0.0
        return priority / representation_tokens

    def score(
        self,
        item: ContextItem,
        *,
        representation: str,
        representation_tokens: int,
    ) -> ItemScore:
        priority, factors = self.priority(item)
        return ItemScore(
            item_id=item.item_id,
            factors=factors,
            priority=round(priority, 6),
            representation=representation,
            representation_tokens=representation_tokens,
            selection_value=round(self.selection_value(priority, representation_tokens), 8),
        )

    # ── 因子实现(全部 [0,1]) ─────────────────────────────────────────────

    @staticmethod
    def _relevance(item: ContextItem) -> float:
        return min(1.0, max(0.0, float(item.relevance)))

    @staticmethod
    def _authority(item: ContextItem) -> float:
        if item.authority_level is not None:
            return min(1.0, max(0.0, float(item.authority_level)))
        by_role = _AUTHORITY_BY_ROLE.get(item.role.value)
        if by_role is not None:
            return by_role
        return _AUTHORITY_BY_TYPE.get(item.item_type, _AUTHORITY_DEFAULT)

    def _freshness(self, item: ContextItem) -> float:
        half_life = _half_life_of(item.item_type)
        if half_life <= 0:
            return 1.0
        observed = _parse_time(item.observed_at)
        reference = self.context.reference_time
        if observed is None or reference is None:
            return 0.5  # 设计稿 §6:时间缺失取中性值
        delta_hours = max(0.0, (reference - observed).total_seconds() / 3600)
        return 0.5 ** (delta_hours / half_life)

    @staticmethod
    def _source_quality(item: ContextItem) -> float:
        if item.item_type == "data_quality":
            return 0.1
        if item.superseded:
            return 0.4
        if item.trusted:
            return 1.0
        return 0.7

    def _task_impact(self, item: ContextItem) -> float:
        if item.item_id in self.context.preferred_ids:
            return 0.5
        if item.item_id in self.context.omit_ids:
            return 0.2
        # 会话语义:用户消息承载当前任务诉求,助手消息承载结论
        if item.conversation and item.role is ContextRole.USER_DATA:
            return 0.5
        if item.conversation:
            return 0.4
        return 0.3

    @staticmethod
    def _citation_dependency(item: ContextItem) -> float:
        return min(1.0, len(item.cited_by) / 3)

    @staticmethod
    def _failure_risk(item: ContextItem) -> float:
        if item.item_type == "tool_failure":
            return 0.7
        return 0.0

    @staticmethod
    def _staleness(item: ContextItem) -> float:
        return 1.0 if item.superseded else 0.0


def _half_life_of(item_type: str) -> float:
    return _HALF_LIFE_HOURS.get(item_type, _DEFAULT_HALF_LIFE_HOURS)


def scorer_from_env(**kwargs: Any) -> MultiFactorScorer | None:
    """``BUDGETED_SCORING=multi-factor-v2`` 时返回 v2 评分器,否则 None(v1)。"""

    import os

    mode = (os.getenv("BUDGETED_SCORING") or "").strip().lower()
    if mode not in {"multi-factor-v2", "multi_factor_v2", "v2"}:
        return None
    scene = kwargs.pop("scene", os.getenv("BUDGETED_SCORING_SCENE", "default"))
    return MultiFactorScorer(scene=scene, **kwargs)
