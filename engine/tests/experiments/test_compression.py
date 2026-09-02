"""压缩用例模块测试:三操作拆分、原生 4×1 计划、工件冻结复用与当前输入分离。

全部使用确定性编译(默认保守口径 + 抽取式摘要),不访问外部模型。
"""

from __future__ import annotations

import shutil

import pytest

from bdlh_runtime.experiments import NATIVE_AGENT_MODE_ID, compression, native_context_run_count
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
        generate_contexts("ctx-showcase-01")  # 非压缩用例数据源的编号一律拒绝
    with pytest.raises(CompressionSessionError):
        generate_contexts("ctx-chat-01")  # 旧长上下文用例已从用例库移除


def test_generate_contexts_creates_zero_agent_runs(compiled_once):
    """只生成上下文:不创建 Agent、Tool 或评判运行(结构保证 + 结果断言)。"""
    result = compiled_once
    assert result.agent_runs_created == 0
    expected_variants = {"full", "recent-turns", "single-summary", "budgeted-hybrid-v1", "budgeted-extractive"}
    assert set(result.artifacts) == expected_variants
    assert result.stats["variant_count"] == 5
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
        assert occurrences == 1, f"{variant_id}: 当前问题出现 {occurrences} 次(应为 1:不进入历史也不重复追加)"


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
async def test_run_native_matrix_4_cells_each_once(compiled_once):
    """运行原生 4×1:复用同批四份工件,4 格各运行 1 次,唯一实现为原生底座。"""
    from bdlh_runtime.experiments.compression import compile_variants, run_native_context_matrix

    session, variants, _ = compression._load_session_bundle(SESSION_ID)
    compiled = compile_variants(session, variants)
    spy: list[tuple] = []
    report = await run_native_context_matrix(
        SESSION_ID, artifacts=compiled, max_agent_steps=5, cell_runner=_fake_cell_runner(spy)
    )
    assert report["unit_count"] == 4
    assert len(report["cells"]) == 4
    assert native_context_run_count() == 4
    # 每格 repeat_index=0
    assert all(cell["repeat_index"] == 0 for cell in report["cells"])
    # 单元覆盖 4 方式 × 1 种统一原生配置
    assert {cell["agent_mode_id"] for cell in report["cells"]} == {NATIVE_AGENT_MODE_ID}
    assert len({cell["context_variant"] for cell in report["cells"]}) == 4


@pytest.mark.asyncio
async def test_all_cells_reuse_same_artifact_hash(compiled_once):
    """全部单元对同一种上下文读取内容和哈希完全相同的冻结工件。"""
    from bdlh_runtime.experiments.compression import compile_variants, run_native_context_matrix

    session, variants, _ = compression._load_session_bundle(SESSION_ID)
    compiled = compile_variants(session, variants)
    spy: list[tuple] = []
    await run_native_context_matrix(SESSION_ID, artifacts=compiled, cell_runner=_fake_cell_runner(spy))
    by_variant: dict[str, set[str]] = {}
    for run_key, artifact_hash, _steps in spy:
        variant = run_key.split(":")[1]
        by_variant.setdefault(variant, set()).add(artifact_hash)
    for variant, hashes in by_variant.items():
        assert len(hashes) == 1, f"{variant}: 不同单元读到了不同的工件哈希 {hashes}"
    # 且与生成阶段冻结的哈希一致(矩阵口径 4×1:抽取式基线不跑 Agent)
    from bdlh_runtime.experiments import CONTEXT_MATRIX_MODES

    for variant_id in CONTEXT_MATRIX_MODES:
        payload = compiled_once.artifacts[variant_id]
        assert by_variant[variant_id] == {payload["compiled_context_hash"]}


@pytest.mark.asyncio
async def test_run_current_combo_single_run(compiled_once):
    from bdlh_runtime.experiments.compression import compile_variants, run_current_combo

    session, variants, _ = compression._load_session_bundle(SESSION_ID)
    compiled = compile_variants(session, variants)
    spy: list[tuple] = []
    cell = await run_current_combo(
        SESSION_ID,
        "budgeted-hybrid-v1",
        NATIVE_AGENT_MODE_ID,
        artifacts=compiled,
        max_agent_steps=5,
        cell_runner=_fake_cell_runner(spy),
    )
    assert len(spy) == 1  # 只运行 1 次
    assert cell.context_variant == "budgeted-hybrid-v1"
    assert cell.agent_mode_id == NATIVE_AGENT_MODE_ID
    assert cell.context_artifact_hash == compiled["budgeted-hybrid-v1"].compiled_context_hash


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
    assert set(compiled) == {
        "full",
        "recent-turns",
        "single-summary",
        "budgeted-hybrid-v1",
        "budgeted-extractive",
    }

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


def test_build_compression_details_counts_and_excerpts():
    """决策摘要:动作计数准确,被压缩/丢弃条目带 60 字内原文摘要,无事件时不炸。"""

    class _Event:
        def __init__(self, event_id: str, content: str):
            self.event_id = event_id
            self.content = content

    artifacts = {
        "budgeted-hybrid-v1": {
            "strategy": "budgeted",
            "original_tokens": 1000,
            "working_tokens": 300,
            "token_budget": 512,
            "required_retained": True,
            "budget_fit": True,
            "kept_event_ids": ["evt-1", "evt-2"],
            "compressed_event_ids": ["evt-3"],
            "referenced_event_ids": ["evt-4"],
            "omitted_event_ids": ["evt-5"],
            "warnings": [],
        },
    }
    events = [_Event(f"evt-{i}", f"事件{i}的内容" + "长" * 80) for i in range(1, 6)]
    row = compression.build_compression_details(artifacts, events=events)["budgeted-hybrid-v1"]
    assert row["counts"] == {"kept": 2, "compressed": 1, "referenced": 1, "omitted": 1}
    assert row["compressed_items"][0]["id"] == "evt-3"
    assert len(row["compressed_items"][0]["excerpt"]) <= 61
    assert row["compressed_items"][0]["excerpt"].endswith("…")
    assert row["omitted_items"][0]["id"] == "evt-5"
    assert row["required_retained"] is True and row["budget_fit"] is True
    # 缺事件来源:摘要为空串,结构完整
    bare = compression.build_compression_details(artifacts, events=())
    assert bare["budgeted-hybrid-v1"]["omitted_items"][0]["excerpt"] == ""


class _FakeLLMSummarizer:
    """生成式摘要替身:返回带标记的确定性文本,记录调用次数。"""

    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, texts, max_tokens, counter):  # noqa: ANN001
        self.calls += 1
        return "【LLM摘要】" + " ".join(text[:32] for text in texts)


def test_summarizer_compressor_uses_llm_and_falls_back():
    """生成式压缩器:LLM 文本优先;空/回退时走内层结构化抽取。"""
    from bdlh_runtime.context.compression import SummarizerCompressor
    from bdlh_runtime.context.models import ContextClassification, ContextItem
    from bdlh_runtime.context.token_count import ConservativeTokenCounter

    item = ContextItem("evt-1", "原始事件内容" * 10, ContextClassification.COMPRESSIBLE, sequence=1)
    counter = ConservativeTokenCounter()

    class _Inner:
        def __init__(self) -> None:
            self.calls = 0

        def compress(self, item, max_tokens, counter):  # noqa: ANN001
            self.calls += 1
            return "[inner] 抽取"

    inner = _Inner()
    fake = _FakeLLMSummarizer()
    out = SummarizerCompressor(fake, inner=inner).compress(item, 64, counter)
    assert out.startswith("【LLM摘要】")
    assert fake.calls == 1 and inner.calls == 0  # LLM 文本优先,不重复走内层

    class _Empty:
        def summarize(self, texts, max_tokens, counter):  # noqa: ANN001
            return ""

    fallback = SummarizerCompressor(_Empty(), inner=inner).compress(item, 64, counter)
    assert fallback == "[inner] 抽取" and inner.calls == 1


def test_generate_compression_method_contexts_two_artifacts():
    """压缩方法对照(生成阶段):注入 Fake 摘要器,两份工件结构齐备且确实不同。

    不走真实 LLM:from_env(llm_summary=True) 在有 env 的环境会产生真实调用,
    单测一律注入替身;真实差异由私有台试跑验证。
    """
    result = compression.generate_compression_method_contexts(SESSION_ID, llm_summarizer=_FakeLLMSummarizer())
    assert result["test_type"] == "COMPRESSION_CASE"
    assert set(result["stats"]["original_tokens"]) == {"budgeted-extractive", "budgeted-hybrid-v1"}
    # 同一输入:压缩前 token 必然一致
    assert (
    result["stats"]["original_tokens"]["budgeted-extractive"]
    == result["stats"]["original_tokens"]["budgeted-hybrid-v1"]
)
    # 摘要文本不同 → 压缩后工作上下文与构建哈希不同
    assert (
    result["stats"]["working_tokens"]["budgeted-hybrid-v1"]
    != result["stats"]["working_tokens"]["budgeted-extractive"]
)
    details = result["compression_details"]["budgeted-hybrid-v1"]
    assert details["counts"]["compressed"] >= 1
    assert isinstance(result["by_variant"]["budgeted-hybrid-v1"]["warnings"], list)


def test_compression_method_on_phase_reports_steps():
    """on_phase 阶段回调:生成阶段按顺序报「构建抽取式 → LLM 摘要」,
    运行阶段额外逐单元报「运行 Agent」——作业进度据此展示当前步骤。"""
    phases: list[str] = []
    compression.generate_compression_method_contexts(
        SESSION_ID, llm_summarizer=_FakeLLMSummarizer(), on_phase=phases.append
    )
    assert [p.split("(")[0] for p in phases] == [
        "构建抽取式压缩上下文",
        "生成 LLM 摘要 · budgeted-hybrid-v1 主算法",
    ]

    run_phases: list[str] = []

    async def fake_runner(session, artifact, agent_mode_id, run_key, max_agent_steps, *, llm=None):
        return {
            "answer": "按最终决定执行。",
            "error": None,
            "tool_calls": [],
            "stop_reason": "FINAL_ANSWER",
            "actual_agent_steps": 1,
            "duration_ms": 5,
        }

    import asyncio

    from bdlh_runtime.experiments.compression import run_compression_method_comparison

    asyncio.run(
        run_compression_method_comparison(
            SESSION_ID,
            cell_runner=fake_runner,
            max_agent_steps=4,
            llm_summarizer=_FakeLLMSummarizer(),
            on_phase=run_phases.append,
        )
    )
    # 前 2 个阶段同生成阶段;随后每个单元开跑前报「运行 Agent · <方法>」
    assert run_phases[:2] == phases
    assert run_phases[2:] == [
        "运行 Agent · budgeted-extractive(抽取式基线,代码,无模型调用) · 第1次",
        "运行 Agent · budgeted-hybrid-v1(混合主算法:代码硬规则+LLM 摘要) · 第1次",
    ]


@pytest.mark.asyncio
async def test_run_compression_method_comparison_two_cells():
    """压缩方法对照(运行阶段):2 个单元,唯一自变量进入 run_configs 与固定条件。"""
    from bdlh_runtime.experiments.compression import COMPRESSION_METHODS, run_compression_method_comparison

    spy: list[str] = []

    async def fake_runner(session, artifact, agent_mode_id, run_key, max_agent_steps, *, llm=None):
        spy.append(run_key)
        return {
            "answer": "按最终决定执行。",
            "error": None,
            "tool_calls": [],
            "stop_reason": "FINAL_ANSWER",
            "actual_agent_steps": 1,
            "duration_ms": 5,
        }

    fake_summarizer = _FakeLLMSummarizer()
    result = await run_compression_method_comparison(
        SESSION_ID, cell_runner=fake_runner, max_agent_steps=4, llm_summarizer=fake_summarizer
    )
    assert result["unit_count"] == 2
    assert len(result["cells"]) == 2
    assert len(spy) == 2
    assert {key.split(":")[1] for key in spy} == set(COMPRESSION_METHODS)
    assert fake_summarizer.calls > 0  # 生成式侧真实调用了摘要器(budgeted 压缩步骤)
    # 唯一自变量进入配置快照与固定条件
    strategies = {payload["context_strategy"] for payload in result["run_configs"].values()}
    assert strategies == {"budgeted-extractive", "budgeted-hybrid-v1"}
    assert result["fixed_conditions"]["independent_variable"] == ["compression_method"]
    assert result["fixed_conditions"]["experiment_definition"] == "compression-method-comparison"
    assert set(result["by_variant"]) == set(COMPRESSION_METHODS)
    assert set(result["compression_details"]) == set(COMPRESSION_METHODS)
    # 注入 LLM 摘要器后,生成式工件的替代文本与抽取式不同 → 构建哈希必然不同
    assert (
    result["frozen_artifact_hashes"]["budgeted-extractive"]
    != result["frozen_artifact_hashes"]["budgeted-hybrid-v1"]
)


class _BatchCapSummarizer:
    """带批量分块摘要的替身:统计 chunk 请求次数,校验 P0-1 上限生效。"""

    def __init__(self) -> None:
        self.batch_calls = 0
        self.item_calls = 0
        self.batch_item_ids: list[str] = []

    def summarize(self, texts, max_tokens, counter):  # noqa: ANN001
        self.item_calls += 1
        return "【逐条摘要】" + " ".join(text[:16] for text in texts)

    def summarize_batch(self, items, *, max_tokens_per_item, counter):  # noqa: ANN001
        self.batch_calls += 1
        self.batch_item_ids.extend(item_id for item_id, _text in items)
        return {item_id: f"【批量摘要】{text[:16]}" for item_id, text in items}


def test_generative_compile_caps_summary_calls_via_batch(monkeypatch):
    """带批量摘要的编译链:长 Session 的 LLM 请求次数 ≤ 配置上限(修复 108 次放大)。"""
    from bdlh_runtime.session import SessionCompiler

    monkeypatch.setenv("LLM_SUMMARY_MAX_CALLS_PER_BUILD", "4")
    session, variants, _ = compression._load_session_bundle("ctx-session-product-evolution-01")
    budgeted_def = next(
            v for v in variants.get("context_variants") or [] if v.get("variant_id") == "budgeted-hybrid-v1"
        )
    fake = _BatchCapSummarizer()
    compiled = SessionCompiler(summarizer=fake).compile(session, budgeted_def, common_rules="规则")
    assert fake.batch_calls <= 4  # 分块请求数受硬上限约束
    assert fake.item_calls == 0  # 映射未覆盖项走抽取式回退,不再逐条调用 LLM
    assert compiled.compiled_messages
    assert compiled.build_model_calls <= 4  # 工件计量与真实请求数一致


def test_generative_prebuild_summarizes_only_budget_candidates():
    """预算放不下的历史不得先送 LLM,避免“先全量总结、后丢弃”。"""
    from bdlh_runtime.context import (
        ContextBuildRequest,
        ContextClassification,
        ContextItem,
        ContextRole,
        ContextStrategy,
    )
    from bdlh_runtime.session import SessionCompiler

    fake = _BatchCapSummarizer()
    compiler = SessionCompiler(summarizer=fake)
    items = [
        ContextItem(
            item_id="system-prompt",
            content="必须遵守规则。",
            classification=ContextClassification.REQUIRED,
            role=ContextRole.SYSTEM,
            priority=100000,
            sequence=-1,
        )
    ]
    items.extend(
        ContextItem(
            item_id=f"history-{index}",
            content=(f"第 {index} 条历史内容。" * 80),
            classification=ContextClassification.COMPRESSIBLE,
            role=ContextRole.USER_DATA,
            priority=20 - index,
            sequence=index,
        )
        for index in range(20)
    )
    request = ContextBuildRequest(
        items=tuple(items),
        token_budget=420,
        strategy=ContextStrategy.BUDGETED,
    )

    compiler._prebuild_summary_map(items, request)

    assert fake.batch_calls == 1
    assert 0 < len(fake.batch_item_ids) < 20
    assert fake.batch_item_ids == [f"history-{index}" for index in range(len(fake.batch_item_ids))]


@pytest.mark.asyncio
async def test_default_cell_runner_llm_unavailable_marks_invalid(monkeypatch):
    """P0-5:llm=None 且 env 未配置 → 按 env 构建失败,单元诚实标记 LLM_UNAVAILABLE。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    session, variants, _ = compression._load_session_bundle(SESSION_ID)
    budgeted_def = next(
            v for v in variants.get("context_variants") or [] if v.get("variant_id") == "budgeted-hybrid-v1"
        )
    from bdlh_runtime.session import SessionCompiler

    artifact = SessionCompiler().compile(session, budgeted_def, common_rules="规则")
    raw = await compression._default_cell_runner(session, artifact, "native-tool-calling", "run-key", 4, llm=None)
    assert raw["error"] and "LLM_UNAVAILABLE" in raw["error"]  # 不伪装为成功
    assert raw["actual_agent_steps"] == 0  # 未进入 Agent 模型循环


@pytest.mark.asyncio
async def test_native_matrix_budget_terminates_remaining_units(monkeypatch):
    """§11.2:LLM 请求超过作业上限 → 剩余单元跳过,budget_terminated 说明原因。"""
    monkeypatch.setenv("MAX_LLM_REQUESTS_PER_JOB", "2")
    session, variants, _ = compression._load_session_bundle(SESSION_ID)

    async def fake_runner(session, artifact, agent_mode_id, run_key, max_agent_steps, *, llm=None):
        return {
            "answer": "按最终决定执行。",
            "error": None,
            "tool_calls": [],
            "stop_reason": "FINAL_ANSWER",
            "actual_agent_steps": 2,
            "duration_ms": 5,
        }

    result = await compression.run_native_context_matrix(SESSION_ID, cell_runner=fake_runner, max_agent_steps=4)
    assert result["budget_terminated"]  # 2 步/格 × 2 格 > 上限 2
    assert len(result["cells"]) == 2  # 第三格前已超限
    assert len(result["skipped_unit_ids"]) == 2  # 剩余两格跳过
    assert result["budget"]["llm_requests"] == 4  # 只累计真实执行单元的步数
    assert "MAX_LLM_REQUESTS_PER_JOB" in result["budget"]["terminated_reason"]


@pytest.mark.asyncio
async def test_method_comparison_budget_counts_build_requests(monkeypatch):
    """§11.2:方法对照的构建期摘要真实请求计入作业预算(缓存命中不计)。"""
    monkeypatch.setenv("MAX_LLM_REQUESTS_PER_JOB", "1")

    class _CountingSummarizer:
        """构建期摘要替身:每格真实调用 1 次(build_model_calls=1)。"""

        def summarize(self, texts, max_tokens, counter):  # noqa: ANN001
            return "【LLM摘要】" + " ".join(text[:16] for text in texts)

        def summarize_batch(self, items, *, max_tokens_per_item, counter):  # noqa: ANN001
            return {item_id: "【批量摘要】" + text[:16] for item_id, text in items}

    ran: list[str] = []

    async def fake_runner(session, artifact, agent_mode_id, run_key, max_agent_steps, *, llm=None):
        ran.append(run_key)
        return {
            "answer": "ok",
            "error": None,
            "tool_calls": [],
            "stop_reason": "FINAL_ANSWER",
            "actual_agent_steps": 2,
            "duration_ms": 5,
        }

    result = await compression.run_compression_method_comparison(
        SESSION_ID, cell_runner=fake_runner, max_agent_steps=4, llm_summarizer=_CountingSummarizer()
    )
    # 抽取式格先执行(2 步 → 累计 2 超上限 1);生成式格前预算已超限 → 跳过
    assert len(ran) == 1
    assert result["budget_terminated"]
    assert result["budget"]["llm_requests"] == 2
    assert len(result["skipped_unit_ids"]) == 1
