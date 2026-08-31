"""公式五(重要度评分)/公式六(性价比选择)与 budgeted-v2 构建测试。

覆盖:权重校验各失败分支、八因子典型取值、确定性、v2 下 distractor
隔离与 required 保留、serializer 的 superseded/cited_by 补全。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from bdlh_runtime.context import (
    SCENE_WEIGHTS,
    ContextAction,
    ContextBuilder,
    ContextBuildRequest,
    ContextClassification,
    ContextItem,
    ContextReport,
    ContextRole,
    ContextStrategy,
    MultiFactorScorer,
    ScoringContext,
    ScoringWeights,
    scorer_from_env,
)
from bdlh_runtime.context.scoring import SCORING_VERSION


def _weights(**overrides: float) -> ScoringWeights:
    base = {"wr": 0.25, "wa": 0.20, "wf": 0.10, "wq": 0.15, "wi": 0.15, "wc": 0.10, "we": 0.05, "ws": 0.10}
    base.update(overrides)
    return ScoringWeights(**base)


# ── 权重校验 ──────────────────────────────────────────────────────────────


def test_all_scene_weights_and_default_are_valid() -> None:
    for weights in list(SCENE_WEIGHTS.values()) + [_weights()]:
        weights.validate()  # 不抛错即通过


def test_weight_sum_not_one_rejected() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        _weights(wr=0.30).validate()


def test_negative_weight_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _weights(wa=-0.01, wf=0.11).validate()


def test_staleness_weight_cap_rejected() -> None:
    with pytest.raises(ValueError, match="ws must be <= 0.3"):
        _weights(ws=0.31, wr=0.24, wf=0.11).validate()


def test_flat_weights_rejected() -> None:
    with pytest.raises(ValueError, match=">= 0.20"):
        _weights(wr=0.15, wa=0.15, wf=0.15, wq=0.15, wi=0.14, wc=0.13, we=0.13).validate()


# ── 八因子典型取值 ────────────────────────────────────────────────────────


def _scored_item(**kwargs) -> ContextItem:
    params = dict(
        item_id="it-1",
        content="内容",
        classification=ContextClassification.COMPRESSIBLE,
        sequence=1,
    )
    params.update(kwargs)
    return ContextItem(**params)


def test_factor_typical_values() -> None:
    reference = datetime(2026, 8, 24, 12, 0, 0)
    scorer = MultiFactorScorer(context=ScoringContext(reference_time=reference))

    # relevance:字段直读并夹取
    assert scorer.priority(_scored_item(relevance=0.7))[1]["relevance"] == 0.7
    assert scorer.priority(_scored_item(relevance=5.0))[1]["relevance"] == 1.0

    # authority:显式优先,否则 role/item_type 默认表
    assert scorer.priority(_scored_item(authority_level=0.3))[1]["authority"] == 0.3
    assert scorer.priority(_scored_item(role=ContextRole.SYSTEM))[1]["authority"] == 1.0
    assert scorer.priority(_scored_item(item_type="news_evidence"))[1]["authority"] == 0.2

    # freshness:半衰期边界 Δt=0 → 1,Δt=half_life → 0.5,缺失 → 0.5 中性
    market_now = _scored_item(item_type="market_observation", observed_at=reference.isoformat())
    market_half = _scored_item(
        item_type="market_observation",
        observed_at=(reference - timedelta(minutes=5)).isoformat(),
    )
    assert scorer.priority(market_now)[1]["freshness"] == 1.0
    assert abs(scorer.priority(market_half)[1]["freshness"] - 0.5) < 1e-9
    assert scorer.priority(_scored_item(item_type="market_observation"))[1]["freshness"] == 0.5
    # user_profile 不衰减
    assert scorer.priority(_scored_item(item_type="user_profile"))[1]["freshness"] == 1.0

    # source_quality:verified 1.0 / 普通 0.7 / superseded 0.4 / data_quality 0.1
    assert scorer.priority(_scored_item(trusted=True))[1]["source_quality"] == 1.0
    assert scorer.priority(_scored_item(trusted=False))[1]["source_quality"] == 0.7
    assert scorer.priority(_scored_item(superseded=True))[1]["source_quality"] == 0.4
    assert scorer.priority(_scored_item(item_type="data_quality"))[1]["source_quality"] == 0.1

    # task_impact:清单优先,其次会话语义(用户消息 0.5 > 助手 0.4 > 工具 0.3)
    listed = MultiFactorScorer(context=ScoringContext(preferred_ids=frozenset({"it-1"})))
    assert listed.priority(_scored_item())[1]["task_impact"] == 0.5
    omitted = MultiFactorScorer(context=ScoringContext(omit_ids=frozenset({"it-1"})))
    assert omitted.priority(_scored_item())[1]["task_impact"] == 0.2
    assert scorer.priority(_scored_item(role=ContextRole.USER_DATA, conversation=True))[1]["task_impact"] == 0.5
    assert scorer.priority(_scored_item(role=ContextRole.ASSISTANT, conversation=True))[1]["task_impact"] == 0.4

    # citation_dependency:被 3 条引用封顶 1.0
    assert scorer.priority(_scored_item(cited_by=("a", "b")))[1]["citation_dependency"] == pytest.approx(2 / 3)
    assert scorer.priority(_scored_item(cited_by=("a", "b", "c")))[1]["citation_dependency"] == 1.0

    # failure_risk / staleness
    assert scorer.priority(_scored_item(item_type="tool_failure"))[1]["failure_risk"] == 0.7
    assert scorer.priority(_scored_item(superseded=True))[1]["staleness"] == 1.0
    assert scorer.priority(_scored_item())[1]["staleness"] == 0.0


def test_priority_clamped_into_unit_interval() -> None:
    scorer = MultiFactorScorer()
    item = _scored_item(role=ContextRole.SYSTEM, item_type="system_constraint")
    priority, _factors = scorer.priority(item)
    assert 0.0 <= priority <= 1.0


def test_selection_value_divides_priority_by_tokens() -> None:
    scorer = MultiFactorScorer()
    assert scorer.selection_value(0.6, 200) == pytest.approx(0.003)
    assert scorer.selection_value(0.9, 0) == 0.0  # 零除保护


def test_scorer_from_env_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BUDGETED_SCORING", raising=False)
    assert scorer_from_env() is None  # 默认 v1
    monkeypatch.setenv("BUDGETED_SCORING", "multi-factor-v2")
    scorer = scorer_from_env()
    assert scorer is not None and scorer.weights.version == SCORING_VERSION
    monkeypatch.setenv("BUDGETED_SCORING", "multi-factor-v2")
    monkeypatch.setenv("BUDGETED_SCORING_SCENE", "market")
    assert scorer_from_env().weights.scene == "market"


# ── v2 构建:确定性 / required / distractor / 预算 ────────────────────────


def _v2_items() -> tuple[ContextItem, ...]:
    long_news = "新闻报道。" * 200
    return (
        ContextItem("rule", "系统规则。", ContextClassification.REQUIRED, role=ContextRole.SYSTEM, sequence=0),
        ContextItem("q", "当前问题。", ContextClassification.REQUIRED, sequence=99),
        ContextItem(
            "short-key",
            "关键约束:必须使用 PostgreSQL。",
            ContextClassification.COMPRESSIBLE,
            sequence=1,
            relevance=0.9,
        ),
        ContextItem("long-news", long_news, ContextClassification.COMPRESSIBLE, sequence=2, relevance=0.3),
        ContextItem("ref-only", "参考材料。", ContextClassification.REFERENCE_ONLY, sequence=3),
        ContextItem("noise", "干扰条目。", ContextClassification.DISTRACTOR, sequence=4),
    )


def _v2_request() -> ContextBuildRequest:
    return ContextBuildRequest(
        items=_v2_items(),
        token_budget=600,
        strategy=ContextStrategy.BUDGETED,
        compression_ratio=0.35,
    )


def test_v2_build_is_deterministic_and_records_scores() -> None:
    builder = ContextBuilder(scorer=MultiFactorScorer())
    first = builder.build(_v2_request())
    second = builder.build(_v2_request())
    assert first.report.decisions == second.report.decisions
    assert first.report.scores == second.report.scores
    assert first.messages == second.messages
    # scores 覆盖全部候选(required/distractor 不进入)
    assert {row.item_id for row in first.report.scores} == {"short-key", "long-news", "ref-only"}
    assert first.report.scoring_version == SCORING_VERSION


def test_v2_keeps_required_and_isolates_distractor_within_budget() -> None:
    builder = ContextBuilder(scorer=MultiFactorScorer())
    result = builder.build(_v2_request())
    report: ContextReport = result.report
    assert report.required_retained
    assert report.budget_fit
    actions = {d.item_id: d.action for d in report.decisions}
    assert actions["noise"] is ContextAction.ISOLATED
    assert actions["rule"] is ContextAction.KEPT
    assert actions["q"] is ContextAction.KEPT
    joined = "\n".join(m.content for m in result.messages)
    assert "干扰条目" not in joined
    assert "关键约束" in joined  # 高相关短条目按 selection_value 胜出


def test_v2_without_scorer_keeps_v1_behavior() -> None:
    """不注入 scorer 时走 v1:无 scores、scoring_version 为空、reason 无 v2 标记。"""

    builder = ContextBuilder()
    result = builder.build(_v2_request())
    assert result.report.scores == ()
    assert result.report.scoring_version == ""
    assert all(not d.reason.startswith("v2 ") for d in result.report.decisions)


def test_v2_high_value_short_item_beats_low_value_long_item() -> None:
    """性价比语义:中优短条目的 selection_value 高于高优长文,预算受限时先入选。"""

    builder = ContextBuilder(scorer=MultiFactorScorer())
    result = builder.build(_v2_request())
    scores = {row.item_id: row for row in result.report.scores}
    decisions = {d.item_id: d for d in result.report.decisions}
    # 短关键条目完整保留;长新闻被压缩或引用,不得完整霸占预算
    assert decisions["short-key"].action is ContextAction.KEPT
    assert decisions["long-news"].action is not ContextAction.KEPT
    assert scores["short-key"].priority > scores["long-news"].priority


def test_v2_reference_representation_is_fallback_only() -> None:
    """引用陷阱(§3.3):引用表示不能凭低分母抢占完整/压缩表示。"""

    items = (
        ContextItem("rule", "规则。", ContextClassification.REQUIRED, role=ContextRole.SYSTEM, sequence=0),
        ContextItem("c-1", "内容一。" * 40, ContextClassification.COMPRESSIBLE, sequence=1, relevance=0.9),
        ContextItem("c-2", "内容二。" * 40, ContextClassification.COMPRESSIBLE, sequence=2, relevance=0.9),
        ContextItem("c-3", "内容三。" * 40, ContextClassification.COMPRESSIBLE, sequence=3, relevance=0.9),
    )
    result = ContextBuilder(scorer=MultiFactorScorer()).build(
        ContextBuildRequest(items=items, token_budget=400, strategy=ContextStrategy.BUDGETED)
    )
    referenced = [d for d in result.report.decisions if d.action is ContextAction.REFERENCED]
    # 预算充足时不应有任何条目被降级为引用
    assert referenced == []
    joined = "\n".join(m.content for m in result.messages)
    assert "[reference source=" not in joined


def test_v2_dependency_closure_adds_reference_for_cited_source() -> None:
    """依赖闭包:被选中条目引用的来源若被省略,至少以引用表示补入。"""

    items = (
        ContextItem("rule", "规则。", ContextClassification.REQUIRED, role=ContextRole.SYSTEM, sequence=0),
        # c-2 的 source_id 指向 c-1(c-1 被 c-2 引用)
        ContextItem("c-1", "基础事实。" * 60, ContextClassification.COMPRESSIBLE, sequence=1, relevance=0.2),
        ContextItem(
            "c-2",
            "结论引用基础事实。" * 10,
            ContextClassification.COMPRESSIBLE,
            sequence=2,
            relevance=0.9,
            source_id="c-1",
        ),
    )
    result = ContextBuilder(scorer=MultiFactorScorer()).build(
        ContextBuildRequest(items=items, token_budget=260, strategy=ContextStrategy.BUDGETED)
    )
    decisions = {d.item_id: d for d in result.report.decisions}
    assert decisions["c-2"].action is not ContextAction.OMITTED
    if decisions["c-1"].action is ContextAction.OMITTED:
        pytest.fail("被引用来源被省略且未补引用表示(依赖闭包失效)")
    # c-1 的 cited_by 由序列化层或显式构造给出 → citation_dependency > 0
    scorer = MultiFactorScorer()
    c1 = next(i for i in items if i.item_id == "c-1")
    c1 = c1.__class__(**{**c1.__dict__, "cited_by": ("c-2",)})
    assert scorer.priority(c1)[1]["citation_dependency"] == pytest.approx(1 / 3)
