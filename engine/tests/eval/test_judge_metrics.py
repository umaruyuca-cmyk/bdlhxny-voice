"""GT-7 判官指标全量扩展:每指标一正一反(构造 call_log 金标)。

直接驱动 ``_apply_generic_metrics``(三组判官共用内核)+ 一条 run_ab_eval
集成断言(schema token 随可见集规模变化)。
"""

from __future__ import annotations

from typing import Any

import pytest

from bdlh_runtime.evaluation.ab_eval import (
    ABCase,
    RunJudgment,
    _agg_runs,
    _apply_generic_metrics,
    _summarize,
    run_ab_eval,
)
from bdlh_runtime.evaluation.frozen_observations import FrozenObservations
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from tests.eval.frozen_fixtures import frozen_payload
from tests.eval.test_run_telemetry import ScriptedToolModel
from tests.helpers_registry import seeded_snapshot


class _Card:
    """判官消费面替身:parameters JSON Schema + 评测轴三列。"""

    def __init__(
        self,
        required: list[str] | None = None,
        *,
        side_effect: str = "none",
        properties: dict[str, Any] | None = None,
    ) -> None:
        props = properties or {name: {"type": "string"} for name in (required or [])}
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": props,
            "required": list(required or []),
            "additionalProperties": False,
        }
        self.side_effect = side_effect
        self.requires_confirmation = side_effect != "none"
        self.risk_level = "low"


QUOTE = _Card(["symbol"])
VALUATION = _Card(["symbol"])
SEND = _Card(["to", "subject", "body"], side_effect="external_action")
SEARCH_META = _Card(["query"])

CARDS = {
    "market.get_realtime_quote": QUOTE,
    "market.get_valuation": VALUATION,
    "mail.send": SEND,
    "search_tools": SEARCH_META,
}


def _case(**kwargs: Any) -> ABCase:
    defaults: dict[str, Any] = dict(
        id="t-01",
        category="测试",
        message="x",
        expected_tools=("market.get_realtime_quote",),
    )
    defaults.update(kwargs)
    return ABCase(**defaults)


def _judge(
    case: ABCase,
    call_seq: list[tuple[str, dict[str, Any]]],
    *,
    attempted: set[str] | None = None,
    successful: set[str] | None = None,
    tool_correct: bool = True,
) -> RunJudgment:
    j = RunJudgment()
    _apply_generic_metrics(
        j,
        case=case,
        call_seq=call_seq,
        attempted=attempted if attempted is not None else {n for n, _ in call_seq},
        successful=successful if successful is not None else {n for n, _ in call_seq},
        cards=CARDS,
        tool_correct=tool_correct,
    )
    return j


# ── 选择组 ─────────────────────────────────────────────────────────────


def test_selection_precision_recall_full_hit() -> None:
    j = _judge(_case(), [("market.get_realtime_quote", {"symbol": "300750"})])
    assert j.selection_precision == 1.0
    assert j.selection_recall == 1.0
    assert j.missed_gold is False and j.extra_calls is False


def test_selection_missed_and_extra() -> None:
    j = _judge(
        _case(),
        [("market.get_valuation", {"symbol": "300750"})],  # 漏金标 + 选了目录内非金标
        successful={"market.get_valuation"},
    )
    assert j.selection_recall == 0.0 and j.missed_gold is True
    assert j.selection_precision == 0.0
    assert j.extra_calls is True


def test_extra_call_counted_when_gold_partial() -> None:
    j = _judge(
        _case(),
        [
            ("market.get_realtime_quote", {"symbol": "300750"}),
            ("market.get_valuation", {"symbol": "300750"}),
        ],
    )
    assert j.selection_recall == 1.0
    assert j.selection_precision == 0.5
    assert j.extra_calls is True and j.missed_gold is False


def test_selection_group_absent_without_gold() -> None:
    j = _judge(_case(expected_tools=()), [("market.get_valuation", {"symbol": "300750"})])
    assert j.selection_precision is None and j.selection_recall is None
    assert j.missed_gold is False and j.extra_calls is False


# ── 幻觉组补充(禁止尝试口径) ──────────────────────────────────────────


def test_forbidden_attempt_counts_attempted_not_executed() -> None:
    case = _case(absent_tools=("mail.send",))
    j = _judge(case, [], attempted={"mail.send"}, successful=set())
    assert j.forbidden_attempts == ["mail.send"]


def test_forbidden_attempt_empty_when_clean() -> None:
    case = _case(absent_tools=("mail.send",))
    j = _judge(case, [("market.get_realtime_quote", {"symbol": "300750"})])
    assert j.forbidden_attempts == []


# ── 参数与流程组 ───────────────────────────────────────────────────────


def test_params_complete_and_type_valid() -> None:
    j = _judge(_case(), [("market.get_realtime_quote", {"symbol": "300750"})])
    assert j.params_complete_rate == 1.0
    assert j.params_type_valid_rate == 1.0


def test_params_incomplete_and_type_invalid() -> None:
    j = _judge(
        _case(),
        [
            ("market.get_realtime_quote", {}),  # 缺必填 symbol(完整率不通过,类型也不通过)
            ("market.get_realtime_quote", {"symbol": 300750}),  # 键在但类型错(完整率通过,类型不通过)
        ],
    )
    assert j.params_complete_rate == 0.5
    assert j.params_type_valid_rate == 0.0


def test_params_factual_gold_match_and_mismatch() -> None:
    case = _case(expected_params={"market.get_realtime_quote": {"symbol": "300750"}})
    ok = _judge(case, [("market.get_realtime_quote", {"symbol": "300750"})])
    bad = _judge(case, [("market.get_realtime_quote", {"symbol": "600519"})])
    assert ok.params_factual_rate == 1.0
    assert bad.params_factual_rate == 0.0


def test_params_factual_none_without_gold() -> None:
    j = _judge(_case(), [("market.get_realtime_quote", {"symbol": "300750"})])
    assert j.params_factual_rate is None


def test_duplicate_call_detected_and_clean() -> None:
    dup = _judge(
        _case(),
        [
            ("market.get_realtime_quote", {"symbol": "300750"}),
            ("market.get_realtime_quote", {"symbol": "300750"}),  # 同 (name,args) 重复
        ],
    )
    clean = _judge(
        _case(),
        [
            ("market.get_realtime_quote", {"symbol": "300750"}),
            ("market.get_realtime_quote", {"symbol": "600519"}),  # 参数不同不算重复
        ],
    )
    assert dup.duplicate_call is True
    assert clean.duplicate_call is False


def test_order_correct_and_wrong() -> None:
    case = _case(expected_order=("market.get_valuation", "market.get_realtime_quote"))
    ok = _judge(case, [("market.get_valuation", {"symbol": "x"}), ("market.get_realtime_quote", {"symbol": "x"})])
    bad = _judge(case, [("market.get_realtime_quote", {"symbol": "x"}), ("market.get_valuation", {"symbol": "x"})])
    assert ok.order_correct is True
    assert bad.order_correct is False


def test_order_none_without_gold() -> None:
    j = _judge(_case(), [("market.get_realtime_quote", {"symbol": "x"})])
    assert j.order_correct is None


# ── 权限与确认组(v1 只判不拦) ─────────────────────────────────────────


def test_unconfirmed_write_flagged_and_confirmed_ok() -> None:
    send_args: dict[str, Any] = {"to": "a@b.c", "subject": "s", "body": "b"}
    unconfirmed = _judge(_case(expected_tools=("mail.send",)), [("mail.send", send_args)])
    confirmed = _judge(
        _case(expected_tools=("mail.send",), confirmation_present=True),
        [("mail.send", send_args)],
    )
    assert unconfirmed.unconfirmed_write is True
    assert confirmed.unconfirmed_write is False


def test_read_tool_never_counts_as_unconfirmed_write() -> None:
    j = _judge(_case(), [("market.get_realtime_quote", {"symbol": "300750"})])
    assert j.unconfirmed_write is False


def test_write_for_query_flagged_and_read_ok() -> None:
    # 只读题(G 全为只读工具)选中写入工具 → 误用;纯读选中 → 不误用
    bad = _judge(
        _case(),
        [("market.get_realtime_quote", {"symbol": "x"}), ("mail.send", {"to": "a", "subject": "s", "body": "b"})],
        successful={"market.get_realtime_quote", "mail.send"},
    )
    ok = _judge(_case(), [("market.get_realtime_quote", {"symbol": "x"})])
    assert bad.write_for_query is True
    assert ok.write_for_query is False


# ── 检索组(v1 按调用记录近似) ─────────────────────────────────────────


def test_search_hit_and_miss() -> None:
    case = _case(expected_search={"needed": True, "gold_tools": ["market.get_realtime_quote"]})
    hit = _judge(case, [("search_tools", {"query": "价格"}), ("market.get_realtime_quote", {"symbol": "x"})])
    miss = _judge(case, [("search_tools", {"query": "价格"}), ("market.get_valuation", {"symbol": "x"})])
    assert hit.search_hit is True and hit.search_then_correct is True
    assert miss.search_hit is False


def test_invalid_and_duplicate_search() -> None:
    case = _case(expected_search={"needed": False})
    j = _judge(
        case,
        [("search_tools", {"query": "a"}), ("search_tools", {"query": "a"})],
    )
    assert j.invalid_search is True
    assert j.duplicate_search is True


def test_search_group_none_when_no_gold_and_no_search() -> None:
    j = _judge(_case(), [("market.get_realtime_quote", {"symbol": "x"})])
    assert j.search_hit is None and j.search_then_correct is None
    assert j.invalid_search is False and j.duplicate_search is False


# ── 聚合与报告 ─────────────────────────────────────────────────────────


def test_group_summary_aggregates_none_safe() -> None:
    runs = [_judge(_case(), [("market.get_realtime_quote", {"symbol": "x"})]) for _ in range(3)]
    summary = _summarize(runs)
    assert summary.selection_precision_mean == 1.0
    assert summary.params_complete_rate == 1.0
    assert summary.order_correct_rate is None  # 无 expected_order 金标 → 不进分母
    assert summary.search_hit_rate is None
    assert summary.unconfirmed_write_rate == 0.0
    assert summary.mean_tools_schema_tokens == 0  # runner 侧填充,判官内核不设


def test_agg_runs_counts_new_flags() -> None:
    flagged = _judge(
        _case(expected_order=("mail.send",)),
        [
            ("mail.send", {"to": "a", "subject": "s", "body": "b"}),
            ("mail.send", {"to": "a", "subject": "s", "body": "b"}),
        ],
        successful={"mail.send"},
    )
    clean = _judge(_case(), [("market.get_realtime_quote", {"symbol": "x"})])
    agg = _agg_runs([flagged, clean])
    assert agg["missed_gold"] == 1
    assert agg["duplicate_call"] == 1
    assert agg["unconfirmed_write"] == 1


def test_load_cases_parses_gt7_gold_keys_and_warns_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    from bdlh_runtime.evaluation.ab_eval import load_cases

    view = {
        "id": "gt7-01",
        "version": 1,
        "title": "GT-7 金标",
        "message": "帮我发邮件",
        "scene": "market",
        "authenticated": True,
        "expectedChecks": {
            "category": "通用目录",
            "expected_tools": ["mail.send"],
            "expected_params": {"mail.send": {"to": "fixed@example.test"}},
            "expected_order": ["mail.send"],
            "expected_search": {"needed": False},
            "confirmation_present": False,
            "totally_unknown_key": 1,
        },
        "steps": [],
        "variants": [
            {
                "variantId": "default",
                "contextStrategy": "budgeted",
                "tokenBudget": 4096,
                "snapshotId": "gt7-01:fixture-v1",
                "snapshotHash": "sha256:x",
            }
        ],
    }
    (case,) = load_cases([view])
    assert case.expected_params == {"mail.send": {"to": "fixed@example.test"}}
    assert case.expected_order == ("mail.send",)
    assert case.expected_search == {"needed": False}
    assert case.confirmation_present is False
    assert "totally_unknown_key" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_schema_tokens_scale_with_visible_set() -> None:
    """集成:工具定义 token 随可见集收窄而下降(裸调用组当轮 schema 估算)。"""

    async def _run(**kwargs: Any):
        from bdlh_runtime.scenarios import disable_all_scenario_packs, enable_scenario_pack

        enable_scenario_pack("finance")
        try:
            return await run_ab_eval(
                llm=ScriptedToolModel(),
                model="glm-4.7-flash",
                cases=[_case()],
                catalog=catalog_from_snapshot(seeded_snapshot()),
                frozen=FrozenObservations(frozen_payload()),
                retry_delay_s=0,
                inter_run_delay_s=0,
                **kwargs,
            )
        finally:
            disable_all_scenario_packs()

    full = await _run(runs_per_case=1, with_react=False)
    narrowed = await _run(runs_per_case=1, with_react=False, visible_tools=["market.get_valuation"])
    full_tokens = full.cases[0].baseline_runs[0].tools_schema_tokens
    narrow_tokens = narrowed.cases[0].baseline_runs[0].tools_schema_tokens
    assert full_tokens > narrow_tokens > 0
