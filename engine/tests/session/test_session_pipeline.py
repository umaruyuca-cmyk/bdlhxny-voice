"""session 包测试:loader / serializer / compiler / mock 调度器 / gold 评测器。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bdlh_runtime.context import ContextStrategy
from bdlh_runtime.session import (
    SessionCompiler,
    SessionMockDispatcher,
    SessionValidationError,
    dispatcher_from_gold,
    grade_compiled_constraints,
    grade_tool_calls,
    judge_session_run,
    load_session,
    load_variants,
    serialize_session,
)

_CASE_DIR = Path(__file__).resolve().parents[2] / "var" / "cases" / "ctx-session-context-engine-debug-01"
_SESSION_PATH = _CASE_DIR / "ctx-session-context-engine-debug-01.session.json"
_VARIANTS_PATH = _CASE_DIR / "ctx-session-context-engine-debug-01.variants.json"
_GOLD_PATH = _CASE_DIR / "gold" / "ctx-session-context-engine-debug-01.gold.json"

_COMMON_RULES = "你是评审助手。只使用允许的只读工具。"


# ── loader ────────────────────────────────────────────────────────────────


def test_load_real_session_validates_and_hashes() -> None:
    session = load_session(_SESSION_PATH)
    assert session.session_id == "ctx-session-context-engine-debug-01"
    assert len(session.events) == 26
    assert session.source_hash.startswith("sha256:")
    assert session.current_question.startswith("请使用只读工具复核")
    assert "file.read" in session.visible_tools


def test_load_session_rejects_non_contiguous_seq(tmp_path: Path) -> None:
    payload = _minimal_session()
    payload["events"][1]["seq"] = 5
    path = tmp_path / "bad.session.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SessionValidationError, match="seq"):
        load_session(path)


def test_load_session_rejects_dangling_tool_call(tmp_path: Path) -> None:
    payload = _minimal_session()
    payload["events"] = payload["events"][:2]  # 丢掉 tool_result
    path = tmp_path / "bad.session.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SessionValidationError, match="没有结果"):
        load_session(path)


def test_load_session_rejects_missing_question(tmp_path: Path) -> None:
    payload = _minimal_session()
    payload["runtime_case"]["current_question"] = ""
    path = tmp_path / "bad.session.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SessionValidationError, match="current_question"):
        load_session(path)


def _minimal_session() -> dict:
    return {
        "schema_version": "1.0",
        "session_id": "minimal",
        "session_version": 1,
        "runtime_case": {"current_question": "现在怎么办?", "visible_tools": ["file.read"]},
        "events": [
            {"seq": 1, "event_id": "evt-0001", "type": "user_message", "role": "user", "content": "开始"},
            {
                "seq": 2,
                "event_id": "evt-0002",
                "type": "tool_call",
                "role": "assistant",
                "call_id": "call-1",
                "tool_name": "file.read",
                "arguments": {"path": "a.md"},
            },
            {
                "seq": 3,
                "event_id": "evt-0003",
                "type": "tool_result",
                "role": "tool",
                "call_id": "call-1",
                "tool_name": "file.read",
                "status": "success",
                "content": "内容",
            },
            {"seq": 4, "event_id": "evt-0004", "type": "assistant_message", "role": "assistant", "content": "结论"},
        ],
    }


# ── serializer ────────────────────────────────────────────────────────────


def test_serialize_pairs_tool_call_with_result_as_untrusted() -> None:
    session = load_session(_SESSION_PATH)
    serialized = serialize_session(session)
    assert len(serialized) < len(session.events)  # 7 个工具对各自合并
    pair = next(entry for entry in serialized if entry.item.item_id == "evt-0003")
    assert pair.event_ids == ("evt-0003", "evt-0004")
    assert "tool_call code.read" in pair.item.content
    assert pair.item.trusted is False
    message = next(entry for entry in serialized if entry.item.item_id == "evt-0001")
    assert message.item.conversation is True
    assert message.item.role.value == "user_data"
    assistant = next(entry for entry in serialized if entry.item.item_id == "evt-0002")
    assert assistant.item.role.value == "assistant"
    # 顺序保持
    sequences = [entry.item.sequence for entry in serialized]
    assert sequences == sorted(sequences)


# ── compiler ──────────────────────────────────────────────────────────────


def test_compile_four_variants_from_one_session_freeze_and_hash() -> None:
    session = load_session(_SESSION_PATH)
    variants = load_variants(_VARIANTS_PATH)
    compiler = SessionCompiler()
    artifacts = {}
    for variant in variants["context_variants"]:
        artifact = compiler.compile(session, variant, common_rules=_COMMON_RULES)
        artifacts[artifact.variant_id] = artifact
        assert artifact.source_session_hash == session.source_hash
        assert artifact.budget_fit
        assert artifact.required_retained
        assert artifact.compiled_context_hash.startswith("sha256:")

    assert set(artifacts) == {"full-session", "recent-window", "single-summary", "budgeted-session"}
    hashes = {artifact.compiled_context_hash for artifact in artifacts.values()}
    assert len(hashes) == 4  # 四份派生输入互不相同
    source_hashes = {artifact.source_session_hash for artifact in artifacts.values()}
    assert len(source_hashes) == 1  # 但来自同一份 Session

    full = artifacts["full-session"]
    assert set(full.kept_event_ids) == set(session.event_ids)  # 完整透传
    recent = artifacts["recent-window"]
    assert len(recent.kept_event_ids) < len(full.kept_event_ids)
    assert len(recent.omitted_event_ids) > 0
    summary = artifacts["single-summary"]
    assert summary.compressed_event_ids  # 更早事件进入一次性摘要
    budgeted = artifacts["budgeted-session"]
    assert budgeted.working_tokens <= budgeted.token_budget

    # 工件字段全集(variants.compiled_context_artifact_required_fields)
    required_fields = set(variants["compiled_context_artifact_required_fields"])
    payload = budgeted.to_payload()
    missing = required_fields - set(payload)
    assert not missing, f"工件缺少字段: {missing}"

    # 事件桶全覆盖:kept+compressed+referenced+omitted == 全部事件
    covered = (
        set(budgeted.kept_event_ids)
        | set(budgeted.compressed_event_ids)
        | set(budgeted.referenced_event_ids)
        | set(budgeted.omitted_event_ids)
    )
    assert covered == set(session.event_ids)


def test_full_session_overflow_raises_window_error(tmp_path: Path) -> None:
    session = load_session(_SESSION_PATH)
    tiny_variant = {
        "variant_id": "full-session",
        "strategy": "full",
        "strategy_version": "full-session-v1",
        "token_budget": 50,
    }
    with pytest.raises(ValueError, match="working context needs"):
        SessionCompiler().compile(session, tiny_variant, common_rules=_COMMON_RULES)


def test_strategy_aliases_map_to_builder_strategies() -> None:
    from bdlh_runtime.session.compiler import STRATEGY_BY_NAME

    assert STRATEGY_BY_NAME["full-session"] is ContextStrategy.FULL
    assert STRATEGY_BY_NAME["recent-window"] is ContextStrategy.RECENT_N
    assert STRATEGY_BY_NAME["single-summary"] is ContextStrategy.SINGLE_SUMMARY
    assert STRATEGY_BY_NAME["budgeted-session"] is ContextStrategy.BUDGETED


# ── mock 调度器 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_matches_fixtures_and_never_leaks_correct_answer() -> None:
    gold = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    dispatcher = dispatcher_from_gold(gold)

    result = await dispatcher("code.read", {"path": "engine/src/bdlh_runtime/session/compiler.py"})
    assert result["status"] == "success"
    assert result["simulated"] is True
    # 返回的是 gold 冻结的真实语料摘要(带路径与行段),不是占位文本
    expected = next(
        f["result"]["content_excerpt"]
        for f in gold["runtime_mock_fixtures"]
        if (f.get("match_arguments") or {}).get("path", "").endswith("session/compiler.py")
    )
    assert result["content_excerpt"] == expected and len(expected) >= 40

    # 错误路径不兜底正确内容
    wrong = await dispatcher("code.read", {"path": "engine/src/not-exist.py"})
    assert wrong["status"] == "error"
    assert wrong["error_code"] == "TOOL_NOT_IN_FIXTURE"  # code.read 无冻结行:工具级未命中
    assert expected not in json.dumps(wrong, ensure_ascii=False)

    unknown = await dispatcher("session.compress_all", {})
    assert unknown["error_code"] == "TOOL_NOT_IN_FIXTURE"

    assert [record.tool_name for record in dispatcher.call_log] == ["code.read", "code.read", "session.compress_all"]


# ── gold 评测器 ────────────────────────────────────────────────────────────


def _plan() -> dict:
    gold = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    return gold


def test_grade_tool_calls_full_plan_hit() -> None:
    gold = _plan()
    calls = [
        ("code.read", {"path": "engine/src/bdlh_runtime/session/compiler.py"}),
        ("code.read", {"path": "engine/src/bdlh_runtime/context/builder.py"}),
        ("code.read", {"path": "engine/src/bdlh_runtime/engine/loop.py"}),
    ]
    judgment = grade_tool_calls(calls, gold["expected_tool_plan"], gold_visible := _visible(gold))
    assert judgment.required_total == 3
    assert judgment.required_hit == 3
    assert judgment.missing_calls == []
    assert judgment.extra_calls == []
    assert judgment.forbidden_calls == []
    assert judgment.nonexistent_tools == []
    assert judgment.ordering_ok
    assert judgment.selection_rate == 1.0


def test_grade_tool_counts_missing_extra_forbidden_nonexistent_repeated() -> None:
    gold = _plan()
    calls = [
        ("code.read", {"path": "错误路径.py"}),  # 名称命中但参数错误
        ("document.summarize", {"doc": "x"}),  # 不必要调用
        ("file.write", {"path": "x.md"}),  # 禁止调用
        ("github.modify_branch", {"branch": "main"}),  # 不存在工具
        ("file.search", {"query": "builder"}),  # 允许的可选调用
        ("file.search", {"query": "builder"}),  # 重复调用
    ]
    judgment = grade_tool_calls(calls, gold["expected_tool_plan"], _visible(gold))
    assert judgment.required_hit == 0
    assert judgment.missing_calls == []  # code.read 名称出现过(参数错误)不算漏调用
    assert judgment.argument_mismatch == ["code.read"] * 3  # 三条 required 同名,参数全部未中
    assert "document.summarize" in judgment.unnecessary_calls
    assert judgment.forbidden_calls == ["file.write"]
    assert "github.modify_branch" in judgment.nonexistent_tools
    assert any(item.startswith("file.searchx") for item in judgment.repeated_calls)


def _visible(gold: dict) -> list[str]:
    session = load_session(_SESSION_PATH)
    return list(session.visible_tools)


def test_judge_session_run_constraint_and_superseded_checks() -> None:
    gold = _plan()
    session = load_session(_SESSION_PATH)
    variants = load_variants(_VARIANTS_PATH)
    variant = next(row for row in variants["context_variants"] if row["variant_id"] == "recent-window")
    compiled = SessionCompiler().compile(session, variant, common_rules=_COMMON_RULES)

    judgment = judge_session_run(
        compiled=compiled,
        gold=gold,
        tool_calls=[],
        answer="结论:四种策略都使用自研压缩算法。",
        visible_tools=session.visible_tools,
    )
    # 本 Session 的约束都在近期窗口内 → 保留率满格(与丢弃场景相对的边界)
    assert judgment.constraint_retention == 1.0
    assert judgment.missing_constraints == []
    # 答案使用禁用说法(gold.forbidden_claims)→ 如实检出;无废弃决定 → 无误用
    assert judgment.forbidden_claims_in_answer == ["四种策略都使用自研压缩算法"]
    assert judgment.superseded_misuse == []
    assert judgment.states_no_file_changes is False


def test_grade_compiled_constraints_full_session_keeps_all() -> None:
    gold = _plan()
    session = load_session(_SESSION_PATH)
    variants = load_variants(_VARIANTS_PATH)
    variant = next(row for row in variants["context_variants"] if row["variant_id"] == "full-session")
    compiled = SessionCompiler().compile(session, variant, common_rules=_COMMON_RULES)
    rate, missing = grade_compiled_constraints(compiled, gold)
    assert rate == 1.0
    assert missing == []


# ── 引用元数据(superseded / cited_by)────────────────────────────────────


def test_serializer_marks_superseded_for_same_source_later_observed_at(tmp_path: Path) -> None:
    payload = _minimal_session()
    payload["events"] = [
        {"seq": 1, "event_id": "evt-1", "type": "user_message", "role": "user", "content": "旧决定",
         "source_id": "dec-a", "occurred_at": "2026-08-20T10:00:00"},
        {"seq": 2, "event_id": "evt-2", "type": "user_message", "role": "user", "content": "新决定",
         "source_id": "dec-a", "occurred_at": "2026-08-21T10:00:00"},
    ]
    path = tmp_path / "superseded.session.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    serialized = serialize_session(load_session(path))
    by_id = {entry.item.item_id: entry.item for entry in serialized}
    assert by_id["evt-1"].superseded is True
    assert by_id["evt-2"].superseded is False


def test_serializer_builds_cited_by_from_source_pointing_to_item_id(tmp_path: Path) -> None:
    payload = _minimal_session()
    payload["events"] = [
        {"seq": 1, "event_id": "evt-1", "type": "user_message", "role": "user", "content": "基础事实",
         "occurred_at": "2026-08-20T10:00:00"},
        {"seq": 2, "event_id": "evt-2", "type": "assistant_message", "role": "assistant", "content": "引用基础事实的结论",
         "source_id": "evt-1", "occurred_at": "2026-08-20T11:00:00"},
    ]
    path = tmp_path / "cited.session.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    serialized = serialize_session(load_session(path))
    by_id = {entry.item.item_id: entry.item for entry in serialized}
    assert by_id["evt-1"].cited_by == ("evt-2",)
    assert by_id["evt-2"].cited_by == ()


def test_serializer_reference_metadata_is_deterministic() -> None:
    session = load_session(_SESSION_PATH)
    first = serialize_session(session)
    second = serialize_session(session)
    assert [entry.item.superseded for entry in first] == [entry.item.superseded for entry in second]
    assert [entry.item.cited_by for entry in first] == [entry.item.cited_by for entry in second]


# ── budgeted-v2 编译工件 ─────────────────────────────────────────────────


def test_v2_scoring_writes_scores_and_version_into_budgeted_artifact_only() -> None:
    """BUDGETED_SCORING=multi-factor-v2 时仅 budgeted-session 升级为 v2;其余变体不受影响。"""

    session = load_session(_SESSION_PATH)
    variants = load_variants(_VARIANTS_PATH)
    compiler = SessionCompiler(
        scorer=__import__("bdlh_runtime.context", fromlist=["MultiFactorScorer"]).MultiFactorScorer()
    )
    strategy_versions = {}
    for variant in variants["context_variants"]:
        artifact = compiler.compile(session, variant, common_rules=_COMMON_RULES)
        payload = artifact.to_payload()
        strategy_versions[variant["variant_id"]] = artifact.strategy_version
        if variant["variant_id"] == "budgeted-session":
            assert artifact.scoring_version == "multi-factor-v2"
            assert artifact.strategy_version == "multi-factor-v2"
            scores = payload["scores"]
            assert scores and all(
                {"item_id", "factors", "priority", "representation", "representation_tokens", "selection_value"}
                <= set(row)
                for row in scores
            )
            assert all(len(row["factors"]) == 8 for row in scores)
            assert artifact.required_retained and artifact.budget_fit
            covered = (
                set(artifact.kept_event_ids)
                | set(artifact.compressed_event_ids)
                | set(artifact.referenced_event_ids)
                | set(artifact.omitted_event_ids)
            )
            assert covered == set(session.event_ids)
        else:
            assert payload["scores"] == []
            assert payload["scoring_version"] == ""
            assert artifact.strategy_version == variant["strategy_version"]
    assert strategy_versions["budgeted-session"] == "multi-factor-v2"


def test_v2_and_v1_are_controlled_contrast_on_real_session() -> None:
    """同 Session 上 v1 与 v2 的预算都满足、required 都保留,排序可不同。"""

    from bdlh_runtime.context import MultiFactorScorer

    session = load_session(_SESSION_PATH)
    variants = load_variants(_VARIANTS_PATH)
    variant = next(row for row in variants["context_variants"] if row["variant_id"] == "budgeted-session")
    v1 = SessionCompiler().compile(session, variant, common_rules=_COMMON_RULES)
    v2 = SessionCompiler(scorer=MultiFactorScorer()).compile(session, variant, common_rules=_COMMON_RULES)
    assert v1.strategy_version == "budgeted-session-v1"
    assert v2.strategy_version == "multi-factor-v2"
    assert v1.compiled_context_hash != v2.compiled_context_hash
    assert v1.required_retained and v2.required_retained
    assert v1.budget_fit and v2.budget_fit


def test_compiled_artifact_records_tokenizer_version() -> None:
    session = load_session(_SESSION_PATH)
    variants = load_variants(_VARIANTS_PATH)
    variant = next(row for row in variants["context_variants"] if row["variant_id"] == "recent-window")
    compiled = SessionCompiler().compile(session, variant, common_rules=_COMMON_RULES)
    assert compiled.tokenizer_version == "conservative-cjk1-latin4-v1"
    assert compiled.to_payload()["tokenizer_version"] == "conservative-cjk1-latin4-v1"
