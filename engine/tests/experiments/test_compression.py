"""压缩用例模块测试:三操作拆分、12 格矩阵、工件冻结复用与当前输入分离。

全部使用确定性编译(默认保守口径 + 抽取式摘要),不访问外部模型。
"""

from __future__ import annotations

import shutil

import pytest

from bdlh_runtime.experiments import compression, compression_session_run_count
from bdlh_runtime.experiments.compression import (
    CompressionSessionError,
    StaleContextArtifactError,
    generate_contexts,
)
from bdlh_runtime.session import load_session

SESSION_ID = "ctx-session-context-engine-debug-01"  # 三个压缩 Session 中最小的一个(26 事件)


@pytest.fixture(scope="module")
def compiled_once():
    """同一批四份冻结工件(模块内共享,等价于「先生成,再运行」的两步操作)。"""
    return generate_contexts(SESSION_ID, write=False)


def test_compression_sessions_are_exactly_three():
    assert [row[0] for row in compression.COMPRESSION_SESSIONS] == [
        "ctx-session-product-evolution-01",
        "ctx-session-context-engine-debug-01",
        "ctx-session-database-deploy-01",
    ]


def test_unknown_session_rejected():
    with pytest.raises(CompressionSessionError):
        generate_contexts("ctx-session-touchstone-design-01")  # 展示用 Session 不属于压缩用例数据源
    with pytest.raises(CompressionSessionError):
        generate_contexts("ctx-chat-01")  # 旧长上下文用例已从用例库移除


def test_generate_contexts_creates_zero_agent_runs(compiled_once):
    """只生成上下文:不创建 Agent、Tool 或评判运行(结构保证 + 结果断言)。"""
    result = compiled_once
    assert result.agent_runs_created == 0
    assert set(result.artifacts) == {"full-session", "recent-window", "single-summary", "budgeted-session"}
    assert result.stats["variant_count"] == 4
    # 每份工件都有内容哈希与 Token 统计(压缩前后口径)
    for payload in result.artifacts.values():
        assert payload["compiled_context_hash"].startswith("sha256:")
        assert payload["original_tokens"] > 0
        assert payload["working_tokens"] > 0


def test_current_input_not_in_history_twice(compiled_once):
    """当前输入只发送一次:最新用户消息不重复进入历史压缩。"""
    session = load_session(compression.session_case_dir(SESSION_ID) / f"{SESSION_ID}.session.json")
    question = session.current_question
    for variant_id, payload in compiled_once.artifacts.items():
        contents = [row["content"] for row in payload["compiled_messages"]]
        joined = "\n".join(contents)
        occurrences = joined.count(question)
        assert occurrences == 1, (
            f"{variant_id}: 当前问题出现 {occurrences} 次(应为 1:不进入历史也不重复追加)"
        )


def test_current_event_is_latest_user_message():
    session = load_session(compression.session_case_dir(SESSION_ID) / f"{SESSION_ID}.session.json")
    event = compression.current_event_of(session)
    assert event.type == "user_message"
    later = [e for e in session.events if e.seq > event.seq]
    assert all(e.type != "user_message" for e in later)  # 其后没有更新的用户消息


def _fake_cell_runner(spy):
    async def runner(session, artifact, agent_mode_id, run_key, max_agent_steps, *, llm=None):
        spy.append((run_key, artifact.compiled_context_hash, max_agent_steps))
        return {
            "answer": "按最终决定,该模块保持只读工具复核。",
            "error": None,
            "tool_calls": [],
            "stop_reason": "FINAL_ANSWER",
            "actual_agent_steps": 1,
            "duration_ms": 5,
        }

    return runner


@pytest.mark.asyncio
async def test_run_full_matrix_12_cells_each_once(compiled_once):
    """运行完整 4×3:复用同批四份工件,12 格各运行 1 次。"""
    from bdlh_runtime.experiments.compression import compile_variants, run_full_matrix

    session, variants, _ = compression._load_session_bundle(SESSION_ID)
    compiled = compile_variants(session, variants)
    spy: list[tuple] = []
    report = await run_full_matrix(
        SESSION_ID, artifacts=compiled, max_agent_steps=5, cell_runner=_fake_cell_runner(spy)
    )
    assert report["unit_count"] == 12
    assert len(report["cells"]) == 12
    assert compression_session_run_count() == 12
    # 每格 repeat_index=0
    assert all(cell["repeat_index"] == 0 for cell in report["cells"])
    # 单元覆盖 4 方式 × 3 Agent
    assert len({(cell["context_variant"], cell["agent_mode_id"]) for cell in report["cells"]}) == 12


@pytest.mark.asyncio
async def test_three_agents_reuse_same_artifact_hash(compiled_once):
    """三种 Agent 对同一种上下文读取内容和哈希完全相同的冻结工件。"""
    from bdlh_runtime.experiments.compression import compile_variants, run_full_matrix

    session, variants, _ = compression._load_session_bundle(SESSION_ID)
    compiled = compile_variants(session, variants)
    spy: list[tuple] = []
    await run_full_matrix(SESSION_ID, artifacts=compiled, cell_runner=_fake_cell_runner(spy))
    by_variant: dict[str, set[str]] = {}
    for run_key, artifact_hash, _steps in spy:
        variant = run_key.split(":")[1]
        by_variant.setdefault(variant, set()).add(artifact_hash)
    for variant, hashes in by_variant.items():
        assert len(hashes) == 1, f"{variant}: 三种 Agent 读到了不同的工件哈希 {hashes}"
    # 且与生成阶段冻结的哈希一致
    for variant_id, payload in compiled_once.artifacts.items():
        assert by_variant[variant_id] == {payload["compiled_context_hash"]}


@pytest.mark.asyncio
async def test_run_current_combo_single_run(compiled_once):
    from bdlh_runtime.experiments.compression import compile_variants, run_current_combo

    session, variants, _ = compression._load_session_bundle(SESSION_ID)
    compiled = compile_variants(session, variants)
    spy: list[tuple] = []
    cell = await run_current_combo(
        SESSION_ID,
        "budgeted-session",
        "full-system",
        artifacts=compiled,
        max_agent_steps=5,
        cell_runner=_fake_cell_runner(spy),
    )
    assert len(spy) == 1  # 只运行 1 次
    assert cell.context_variant == "budgeted-session"
    assert cell.agent_mode_id == "full-system"
    assert cell.context_artifact_hash == compiled["budgeted-session"].compiled_context_hash


def test_stale_artifacts_rejected_after_session_change(tmp_path, monkeypatch):
    """Session/参数变化后旧工件不能静默复用;必须提示重新生成。"""
    case_src = compression.session_case_dir(SESSION_ID)
    case_dst = tmp_path / SESSION_ID
    shutil.copytree(case_src, case_dst)
    shutil.rmtree(case_dst / "compiled", ignore_errors=True)  # 源目录可能已有真实运行产物
    monkeypatch.setattr(compression, "CASES_ROOT", tmp_path)

    # 1) 先正常生成并落盘
    result = generate_contexts(SESSION_ID, write=False)
    compiled_dir = case_dst / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    for variant_id, payload in result.artifacts.items():
        (compiled_dir / f"{variant_id}.json").write_text(
            __import__("json").dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    (compiled_dir / "fingerprint.json").write_text(
        __import__("json").dumps(result.fingerprint, ensure_ascii=False), encoding="utf-8"
    )

    # 2) 未变化:可加载(确定性构建哈希一致)
    session, variants, compiled = compression._load_frozen_batch(SESSION_ID)
    assert set(compiled) == {"full-session", "recent-window", "single-summary", "budgeted-session"}

    # 3) Session 内容变化(追加一轮对话)→ source_hash 变化 → 拒绝复用
    import json as _json

    session_file = case_dst / f"{SESSION_ID}.session.json"
    raw = _json.loads(session_file.read_text(encoding="utf-8"))
    raw["events"].append(
        {
            "seq": len(raw["events"]) + 1,
            "event_id": f"evt-extra-{len(raw['events']) + 1}",
            "occurred_at": "2026-08-25T10:00:00+08:00",
            "type": "user_message",
            "role": "user",
            "content": "补充:下季度再复核一次。",
        }
    )
    session_file.write_text(_json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(StaleContextArtifactError):
        compression._load_frozen_batch(SESSION_ID)


def test_missing_artifacts_rejected(tmp_path, monkeypatch):
    real_root = compression.CASES_ROOT
    src = real_root / SESSION_ID
    monkeypatch.setattr(compression, "CASES_ROOT", tmp_path)
    shutil.copytree(src, tmp_path / SESSION_ID)
    shutil.rmtree(tmp_path / SESSION_ID / "compiled", ignore_errors=True)  # 同上:不依赖源目录运行时状态
    # 没有 compiled/fingerprint.json → 提示先生成
    with pytest.raises(StaleContextArtifactError):
        compression._load_frozen_batch(SESSION_ID)


def test_public_session_overview_three_sessions_only():
    overview = compression.public_session_overview()
    assert len(overview) == 3
    assert {row["session_id"] for row in overview} == {row[0] for row in compression.COMPRESSION_SESSIONS}
    for row in overview:
        assert row["current_event_id"]
        assert row["current_message_excerpt"]
        # 公开概览不包含 gold 或评判配置
        assert "gold" not in row and "expected" not in row
