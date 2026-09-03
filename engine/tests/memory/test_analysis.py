"""P2 定时分析任务的单元测试:语义评审器、阈值对照、成本收益、相关性、编排。

全部使用假评审器与假数据客户端,不调用真实 LLM、不触网。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from bdlh_runtime.data_client import DataServiceError
from bdlh_runtime.memory.analysis import (
    SEGMENT_JUDGE_PROMPT_VERSION,
    AnalysisConfigError,
    AnalysisSettings,
    LLMSegmentJudge,
    compression_agent_correlation,
    cost_benefit,
    load_segment_judge_prompt,
    run_analysis,
    threshold_groups,
)
from bdlh_runtime.memory.analysis import SegmentJudgeVerdict as Verdict


class _FakeLLM:
    """按预设内容返回;可注入异常。"""

    def __init__(self, content: Any, fail: Exception | None = None) -> None:
        self.content = content
        self.fail = fail
        self.prompts: list[str] = []

    def invoke(self, messages, **_kwargs):  # noqa: ANN001
        self.prompts.append(str(messages))
        if self.fail is not None:
            raise self.fail
        if isinstance(self.content, Exception):
            raise self.content
        return AIMessage(content=self.content)


class _FakeJudge:
    """假评审器:按序返回预设结论。"""

    def __init__(self, verdicts: list[Verdict]) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[dict[str, str]] = []

    def judge(self, *, summary: str, source_text: str) -> Verdict:
        self.calls.append({"summary": summary, "source_text": source_text})
        return self._verdicts.pop(0) if self._verdicts else Verdict(verdict="PASS")


class _FakeData:
    """假数据客户端:记录分析运行与抽检落库,返回固定采样源。"""

    def __init__(self, segments: list[dict[str, Any]] | None = None, builds: list[dict[str, Any]] | None = None):
        self.segments = segments or []
        self.builds = builds or []
        self.started_runs: list[str] = []
        self.finished: list[tuple[str, dict[str, Any]]] = []
        self.saved_checks: list[dict[str, Any]] = []
        self.fail_start = False

    def start_context_analysis_run(self, trigger: str) -> str:
        if self.fail_start:
            raise DataServiceError("data service down")
        self.started_runs.append(trigger)
        return "run-1"

    def finish_context_analysis_run(self, run_id: str, payload: dict[str, Any]) -> None:
        self.finished.append((run_id, payload))

    def list_recent_context_segments(self, limit: int) -> list[dict[str, Any]]:  # noqa: ARG002
        return self.segments

    def save_context_quality_check(self, payload: dict[str, Any]) -> None:
        self.saved_checks.append(payload)

    def list_context_builds_cross_owner(self, limit: int, cursor: int) -> dict[str, Any]:  # noqa: ARG002
        return {"builds": self.builds, "total": len(self.builds), "nextCursor": None}


def _segment_row(segment_id: str = "seg-1", *, contents: str = '["原文一", "原文二"]') -> dict[str, Any]:
    return {
        "segmentId": segment_id,
        "sessionId": "s1",
        "accountId": "10000000-0000-0000-0000-000000000001",
        "summaryContent": "摘要正文",
        "sourceHash": "sha256:seg",
        "sourceContents": contents,
    }


def _build_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "status": "COMPLETED",
        "config_snapshot": {
            "algorithm_version": "budgeted-hybrid-v1",
            "recent_raw_turns": 2,
            "segment_max_tokens": 512,
            "summary_call_cap": 2,
        },
        "budget": {"history_input_tokens": 1000, "final_context_tokens": 400},
        "llm_usage": {"summary_calls": 1, "cache_hits": 1, "segment_model_calls": 0, "agent_calls": 0},
        "agent_run": None,
    }
    row.update(overrides)
    return row


# ── 评审器 ──


def test_judge_prompt_loads_from_file() -> None:
    prompt = load_segment_judge_prompt()
    assert "质量评审员" in prompt
    assert "verdict" in prompt


def test_llm_judge_parses_valid_verdict() -> None:
    llm = _FakeLLM('{"verdict":"WARN","missing_facts":["漏了决定"],"hallucinations":[],"note":"ok"}')
    judge = LLMSegmentJudge(llm=llm)
    verdict = judge.judge(summary="摘要", source_text="原文")
    assert verdict.verdict == "WARN"
    assert verdict.missing_facts == ("漏了决定",)
    assert verdict.hallucinations == ()
    assert verdict.note == "ok"
    assert verdict.error_code is None
    # 提示包含来源原文与摘要,且来自提示文件
    assert "来源原文" in llm.prompts[0] and "原文" in llm.prompts[0]
    assert "质量评审员" in llm.prompts[0]


def test_llm_judge_tolerates_fenced_json() -> None:
    llm = _FakeLLM('```json\n{"verdict":"PASS","missing_facts":[],"hallucinations":[]}\n```')
    verdict = LLMSegmentJudge(llm=llm).judge(summary="s", source_text="t")
    assert verdict.verdict == "PASS"


def test_llm_judge_invalid_output_is_error_not_guess() -> None:
    for content in ("不是 JSON", '{"verdict":"MAYBE"}', '["数组不是对象"]'):
        verdict = LLMSegmentJudge(llm=_FakeLLM(content)).judge(summary="s", source_text="t")
        assert verdict.verdict == "ERROR"
        assert verdict.error_code == "LLM_INVALID_OUTPUT"


def test_llm_judge_classifies_failures() -> None:
    timeout = LLMSegmentJudge(llm=_FakeLLM(None, fail=RuntimeError("request timed out")))
    assert timeout.judge(summary="s", source_text="t").error_code == "LLM_TIMEOUT"


def test_llm_judge_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    verdict = LLMSegmentJudge().judge(summary="s", source_text="t")
    assert verdict.verdict == "ERROR"
    assert verdict.error_code == "LLM_UNAVAILABLE"


# ── 阈值对照 / 成本收益 / 相关性 ──


def test_threshold_groups_split_by_frozen_config() -> None:
    builds = [
        _build_row(),
        _build_row(
            config_snapshot={
                "algorithm_version": "budgeted-hybrid-v1",
                "recent_raw_turns": 2,
                "segment_max_tokens": 512,
                "summary_call_cap": 2,
            }
        ),
        _build_row(
            config_snapshot={
                "algorithm_version": "budgeted-hybrid-v1",
                "recent_raw_turns": 4,
                "segment_max_tokens": 512,
                "summary_call_cap": 2,
            }
        ),
        _build_row(status="FAILED"),
    ]
    groups = threshold_groups(builds)
    assert len(groups) == 2  # recent_raw_turns=2 一组(3 构建),=4 一组(1 构建)
    big = next(row for row in groups if row["build_count"] == 3)
    small = next(row for row in groups if row["build_count"] == 1)
    assert big["recent_raw_turns"] == 2 and small["recent_raw_turns"] == 4
    assert big["completed_count"] == 2  # FAILED 不计入完成
    assert big["avg_compression_rate"] == 0.6  # 仅完成构建:(0.6+0.6)/2
    assert big["avg_raw_tokens"] == 1000.0 and big["avg_final_tokens"] == 400.0
    # 调用成本按全部构建累计——失败构建同样真实消耗了 LLM 调用
    assert big["total_summary_calls"] == 3 and big["total_cache_hits"] == 3
    # 旧构建快照缺键 → unknown 组,不与已知组合并
    legacy = threshold_groups([{"status": "COMPLETED", "budget": {}, "llm_usage": {}}])
    assert legacy[0]["recent_raw_turns"] is None and legacy[0]["algorithm_version"] == "unknown"


def test_cost_benefit_shows_savings_and_costs_together() -> None:
    builds = [
        _build_row(),
        _build_row(budget={"history_input_tokens": 800, "final_context_tokens": 500}),
        _build_row(status="FAILED"),  # 失败构建不进节省口径
    ]
    report = cost_benefit(builds)
    assert report["completed_builds"] == 2
    assert report["token_savings"] == 900  # (1000-400)+(800-500)
    assert report["generation_llm_calls"] == 2
    assert report["generation_breakdown"] == {"summary_calls": 2, "segment_model_calls": 0}
    assert report["token_savings_per_generation_call"] == 450.0
    assert report["agent_llm_calls"] == 0


def test_cost_benefit_no_calls_has_null_ratio() -> None:
    report = cost_benefit([_build_row(llm_usage={"summary_calls": 0})])
    assert report["token_savings_per_generation_call"] is None


def test_correlation_requires_min_samples() -> None:
    one = compression_agent_correlation([_build_row(agent_run={"status": "COMPLETED", "steps": 2})])
    assert one["correlation"] is None
    assert one["sample_count"] == 1
    assert "样本不足" in one["note"] or "还没有" in one["note"]

    builds = [
        _build_row(
            budget={"history_input_tokens": 1000, "final_context_tokens": 900},
            agent_run={"status": "COMPLETED", "steps": 1},
        ),  # rate 0.1
        _build_row(
            budget={"history_input_tokens": 1000, "final_context_tokens": 500},
            agent_run={"status": "COMPLETED", "steps": 2},
        ),  # rate 0.5
        _build_row(
            budget={"history_input_tokens": 1000, "final_context_tokens": 100},
            agent_run={"status": "COMPLETED", "steps": 3},
        ),  # rate 0.9
    ]
    report = compression_agent_correlation(builds)
    assert report["sample_count"] == 3
    assert report["correlation"] == 1.0  # 完全正相关
    # 未完成/无 Agent 运行的构建不进样本
    mixed = compression_agent_correlation([*builds, _build_row(status="FAILED")])
    assert mixed["sample_count"] == 3


# ── 编排 ──


def test_run_analysis_samples_judges_and_persists() -> None:
    data = _FakeData(
        segments=[_segment_row("seg-1"), _segment_row("seg-2")],
        builds=[_build_row()],
    )
    judge = _FakeJudge(
        [
            Verdict(verdict="PASS"),
            Verdict(verdict="FAIL", missing_facts=("漏了约束",), hallucinations=("编造数字",)),
        ]
    )

    outcome = run_analysis(data, judge, settings=AnalysisSettings(sample_size=5), trigger="MANUAL")

    assert outcome.status == "COMPLETED"
    assert outcome.sampled == 2 and outcome.judge_calls == 2 and outcome.judge_errors == 0
    assert data.started_runs == ["MANUAL"]
    # 评审输入:摘要 + 来源原文拼接
    assert judge.calls[0]["summary"] == "摘要正文"
    assert "原文一" in judge.calls[0]["source_text"]
    # 抽检结果逐段落库,提示词版本与来源哈希随行
    assert [row["segmentId"] for row in data.saved_checks] == ["seg-1", "seg-2"]
    assert data.saved_checks[1]["verdict"] == "FAIL"
    assert data.saved_checks[1]["missingFacts"] == ["漏了约束"]
    assert data.saved_checks[1]["promptVersion"] == SEGMENT_JUDGE_PROMPT_VERSION
    # 终态写入:COMPLETED + 报告四节齐全
    run_id, payload = data.finished[0]
    assert run_id == "run-1" and payload["status"] == "COMPLETED"
    assert set(payload["report"]) == {"quality_sampling", "threshold_groups", "cost_benefit", "correlation"}
    assert payload["report"]["quality_sampling"]["verdict_counts"]["FAIL"] == 1
    assert payload["report"]["quality_sampling"]["worst_verdict"] == "FAIL"
    assert payload["report"]["threshold_groups"][0]["build_count"] == 1


def test_run_analysis_partial_judge_errors_still_completes() -> None:
    """部分段评审失败:结果如实落库,运行整体仍 COMPLETED(有有效信号)。"""

    data = _FakeData(segments=[_segment_row("seg-1"), _segment_row("seg-2")])
    judge = _FakeJudge(
        [
            Verdict(verdict="PASS"),
            Verdict(verdict="ERROR", error_code="LLM_UNAVAILABLE"),
        ]
    )

    outcome = run_analysis(data, judge, settings=AnalysisSettings(sample_size=3))

    assert outcome.status == "COMPLETED"
    assert outcome.judge_errors == 1 and outcome.judge_calls == 1
    assert data.saved_checks[1]["verdict"] == "ERROR"
    assert data.saved_checks[1]["errorCode"] == "LLM_UNAVAILABLE"


def test_run_analysis_all_judge_errors_fails_run() -> None:
    """全部采样段评审失败(如未配置 LLM):运行判 FAILED,不伪装成功。"""

    data = _FakeData(segments=[_segment_row()])
    judge = _FakeJudge([Verdict(verdict="ERROR", error_code="LLM_UNAVAILABLE")])

    outcome = run_analysis(data, judge, settings=AnalysisSettings(sample_size=3))

    assert outcome.status == "FAILED"
    assert outcome.error_code == "JUDGE_ALL_FAILED"
    assert data.saved_checks[0]["verdict"] == "ERROR"
    assert data.finished[0][1]["status"] == "FAILED"


def test_run_analysis_fails_when_start_unavailable() -> None:
    data = _FakeData()
    data.fail_start = True
    outcome = run_analysis(data, _FakeJudge([]), settings=AnalysisSettings(sample_size=1))
    assert outcome.status == "FAILED"
    assert outcome.error_code and outcome.error_code.startswith("DATA_SERVICE_ERROR")


def test_run_analysis_data_failure_freezes_failed_run() -> None:
    data = _FakeData()
    data.list_recent_context_segments = lambda limit: (_ for _ in ()).throw(DataServiceError("down"))
    outcome = run_analysis(data, _FakeJudge([]), settings=AnalysisSettings(sample_size=1))
    assert outcome.status == "FAILED"
    assert data.finished[0][1]["status"] == "FAILED"
    assert data.finished[0][1]["errorCode"].startswith("DATA_SERVICE_ERROR")


def test_analysis_settings_parse_and_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    assert AnalysisSettings.from_env().sample_size == 5
    monkeypatch.setenv("CONTEXT_ANALYSIS_SAMPLE_SIZE", "3")
    monkeypatch.setenv("CONTEXT_ANALYSIS_INTERVAL_S", "0")
    settings = AnalysisSettings.from_env()
    assert settings.sample_size == 3 and settings.interval_s == 0
    monkeypatch.setenv("CONTEXT_ANALYSIS_SAMPLE_SIZE", "0")
    with pytest.raises(AnalysisConfigError):
        AnalysisSettings.from_env()
    monkeypatch.setenv("CONTEXT_ANALYSIS_SAMPLE_SIZE", "abc")
    with pytest.raises(AnalysisConfigError):
        AnalysisSettings.from_env()
