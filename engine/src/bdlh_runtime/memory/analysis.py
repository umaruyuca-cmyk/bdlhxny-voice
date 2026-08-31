"""P2 定时分析任务:摘要段语义质量抽检 + 阈值/预算对照与成本收益分析。

两个能力(需求 §23 P2):
- **语义抽检**:采样最近冻结摘要段,由评审模型对比摘要与来源原文
  (PASS/WARN/FAIL + 遗漏/编造清单);评审失败记 ERROR,不伪造通过;
- **阈值/预算对照 + 成本收益**:从构建快照的真实计量计算按配置分组的
  对照表、Token 节省与生成成本、压缩率与 Agent 表现的相关性。

纪律:
- 评审器是可注入协议,单测用假实现,不调用真实 LLM;
- 分析只读既有构建快照,全部数值为真实计数;样本不足时相关性返回
  None(如实展示"样本不足",不硬算);
- 运行结果持久化到 data service(context_analysis_runs /
  context_segment_quality_checks),页面读取持久化结果,不在页面加载时
  触发任何 LLM 调用。
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from bdlh_runtime.data_client import DataClient, DataServiceError
from bdlh_runtime.infra.llm import DEFAULT_LLM_MODEL, create_llm

SEGMENT_JUDGE_PROMPT_VERSION = "segment-judge-v1"

_JUDGE_PROMPT_FILE = "segment_quality_judge.md"
_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

#: 定时分析默认配置(可用环境变量覆盖;间隔<=0 关闭调度)
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_ANALYSIS_INTERVAL_S = 21600.0  # 6 小时
DEFAULT_ANALYSIS_INITIAL_DELAY_S = 60.0
#: 相关性分析的最小样本数;不足时返回 None,不硬算
MIN_CORRELATION_SAMPLES = 3

_VERDICTS = frozenset({"PASS", "WARN", "FAIL"})
_VERDICT_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2, "ERROR": 3}


class AnalysisConfigError(ValueError):
    """定时分析配置非法(采样数/间隔)。"""


@dataclass(frozen=True)
class AnalysisSettings:
    """定时分析运行配置;非法值在解析处失败,不静默采用默认。"""

    sample_size: int = DEFAULT_SAMPLE_SIZE
    interval_s: float = DEFAULT_ANALYSIS_INTERVAL_S
    initial_delay_s: float = DEFAULT_ANALYSIS_INITIAL_DELAY_S

    @staticmethod
    def from_env() -> AnalysisSettings:
        def _int(name: str, default: int, *, minimum: int = 1) -> int:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise AnalysisConfigError(f"{name} 必须是整数,收到 {raw!r}") from exc
            if value < minimum:
                raise AnalysisConfigError(f"{name} 不能小于 {minimum},收到 {value}")
            return value

        def _float(name: str, default: float, *, minimum: float = 0.0) -> float:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return default
            try:
                value = float(raw)
            except ValueError as exc:
                raise AnalysisConfigError(f"{name} 必须是数值,收到 {raw!r}") from exc
            if value < minimum:
                raise AnalysisConfigError(f"{name} 不能为负,收到 {value}")
            return value

        return AnalysisSettings(
            sample_size=_int("CONTEXT_ANALYSIS_SAMPLE_SIZE", DEFAULT_SAMPLE_SIZE),
            interval_s=_float("CONTEXT_ANALYSIS_INTERVAL_S", DEFAULT_ANALYSIS_INTERVAL_S),
            initial_delay_s=_float("CONTEXT_ANALYSIS_INITIAL_DELAY_S", DEFAULT_ANALYSIS_INITIAL_DELAY_S),
        )


@dataclass(frozen=True)
class SegmentJudgeVerdict:
    """一段摘要的语义评审结论。"""

    verdict: str  # PASS | WARN | FAIL | ERROR
    missing_facts: tuple[str, ...] = ()
    hallucinations: tuple[str, ...] = ()
    note: str = ""
    error_code: str | None = None
    duration_ms: int = 0


class SegmentQualityJudge(Protocol):
    """评审器契约;单测注入假实现,不触网。"""

    def judge(self, *, summary: str, source_text: str) -> SegmentJudgeVerdict: ...


def load_segment_judge_prompt() -> str:
    """加载评审系统提示;文件缺失直接失败,禁止内联兜底。"""

    path = _PROMPTS_DIR / _JUDGE_PROMPT_FILE
    if not path.is_file():
        raise FileNotFoundError(f"评审提示文件缺失:{path}")
    return path.read_text(encoding="utf-8").strip()


class LLMSegmentJudge:
    """经统一 LLM 基建的摘要评审器;结构化 JSON 输出,失败不伪造结论。"""

    def __init__(self, *, llm: Any | None = None, model: str | None = None) -> None:
        self._llm_override = llm
        self._model_override = model

    def _ensure_llm(self) -> Any | None:
        if self._llm_override is not None:
            return self._llm_override
        if not (os.environ.get("LLM_API_KEY") or "").strip():
            return None
        return create_llm(
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL"),
            model=os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL,
            temperature=0,
            max_retries=0,
        )

    def judge(self, *, summary: str, source_text: str) -> SegmentJudgeVerdict:
        llm = self._ensure_llm()
        if llm is None:
            return SegmentJudgeVerdict(
                verdict="ERROR", error_code="LLM_UNAVAILABLE", note="未配置 LLM_API_KEY,评审未执行"
            )
        prompt = (
            f"{load_segment_judge_prompt()}\n\n=== 来源原文 ===\n{source_text}\n\n"
            f"=== 轮摘要 ===\n{summary}\n\n请按规则输出 JSON。"
        )
        started = time.perf_counter()
        try:
            response = llm.invoke([{"role": "user", "content": prompt}])
        except Exception as exc:  # noqa: BLE001 —— 评审失败记 ERROR,不中断整轮分析
            return SegmentJudgeVerdict(
                verdict="ERROR",
                error_code=classify_judge_error(exc),
                note=str(exc),
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
        duration_ms = round((time.perf_counter() - started) * 1000)
        content = getattr(response, "content", response)
        if not isinstance(content, str):
            content = str(content)
        parsed = _parse_judge_json(content)
        if parsed is None:
            return SegmentJudgeVerdict(
                verdict="ERROR",
                error_code="LLM_INVALID_OUTPUT",
                note=f"评审输出不是合法 JSON:{content[:200]}",
                duration_ms=duration_ms,
            )
        verdict = str(parsed.get("verdict") or "").upper()
        if verdict not in _VERDICTS:
            return SegmentJudgeVerdict(
                verdict="ERROR",
                error_code="LLM_INVALID_OUTPUT",
                note=f"verdict 非法:{verdict!r}",
                duration_ms=duration_ms,
            )
        return SegmentJudgeVerdict(
            verdict=verdict,
            missing_facts=tuple(str(row) for row in parsed.get("missing_facts") or []),
            hallucinations=tuple(str(row) for row in parsed.get("hallucinations") or []),
            note=str(parsed.get("note") or ""),
            duration_ms=duration_ms,
        )


def classify_judge_error(exc: Exception) -> str:
    """评审 LLM 失败 → 稳定错误码(与 agent_run 同口径)。"""

    text = f"{type(exc).__name__} {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return "LLM_TIMEOUT"
    if "rate" in text and "limit" in text:
        return "LLM_RATE_LIMITED"
    if "quota" in text or "balance" in text or "余额" in text:
        return "LLM_QUOTA_EXHAUSTED"
    return "LLM_UNAVAILABLE"


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _parse_judge_json(content: str) -> dict[str, Any] | None:
    """容忍 ```json 围栏;解析失败返回 None(调用方记 LLM_INVALID_OUTPUT)。"""

    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(text)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


# ── 分析纯函数:阈值/预算对照、成本收益、相关性(全部基于构建快照真实计数) ──


def _num(value: Any) -> float:
    try:
        return float(value)  # None/非数值 → 异常由调用方保证不发生(默认 0)
    except (TypeError, ValueError):
        return 0.0


def threshold_groups(builds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按构建时冻结的阈值配置分组对照(需求 §23 P2)。

    分组键取 config_snapshot 中的 algorithm_version / recent_raw_turns /
    segment_max_tokens / summary_call_cap——不同阈值跑出的构建各自成组;
    快照缺键的旧构建归入 "unknown" 组,不与已知组合并。
    """

    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in builds:
        config = row.get("config_snapshot") if isinstance(row.get("config_snapshot"), dict) else {}
        usage = row.get("llm_usage") if isinstance(row.get("llm_usage"), dict) else {}
        budget = row.get("budget") if isinstance(row.get("budget"), dict) else {}
        raw = _num(budget.get("history_input_tokens"))
        final = _num(budget.get("final_context_tokens"))
        rate = (1 - final / raw) if raw > 0 else None
        key = (
            str(config.get("algorithm_version") or "unknown"),
            str(config.get("recent_raw_turns") if config.get("recent_raw_turns") is not None else "unknown"),
            str(config.get("segment_max_tokens") if config.get("segment_max_tokens") is not None else "unknown"),
            str(config.get("summary_call_cap") if config.get("summary_call_cap") is not None else "unknown"),
        )
        bucket = groups.setdefault(
            key,
            {
                "algorithm_version": key[0],
                "recent_raw_turns": config.get("recent_raw_turns"),
                "segment_max_tokens": config.get("segment_max_tokens"),
                "summary_call_cap": config.get("summary_call_cap"),
                "build_count": 0,
                "completed_count": 0,
                "_rates": [],
                "_raw": 0.0,
                "_final": 0.0,
                "_summary_calls": 0,
                "_cache_hits": 0,
                "_agent_calls": 0,
            },
        )
        bucket["build_count"] += 1
        # 预算均值只按 COMPLETED 构建(失败构建的预算快照可能为空/无效);
        # LLM 调用成本按全部构建累计——失败构建同样真实消耗了调用
        if str(row.get("status") or "") == "COMPLETED":
            bucket["completed_count"] += 1
            if rate is not None:
                bucket["_rates"].append(rate)
            bucket["_raw"] += raw
            bucket["_final"] += final
        bucket["_summary_calls"] += int(_num(usage.get("summary_calls")))
        bucket["_cache_hits"] += int(_num(usage.get("cache_hits")))
        bucket["_agent_calls"] += int(_num(usage.get("agent_calls")))

    rows: list[dict[str, Any]] = []
    for bucket in groups.values():
        rates = bucket.pop("_rates")
        rows.append(
            {
                **{key: value for key, value in bucket.items() if not key.startswith("_")},
                "avg_compression_rate": round(sum(rates) / len(rates), 4) if rates else None,
                "avg_raw_tokens": round(bucket["_raw"] / bucket["completed_count"], 1)
                if bucket["completed_count"]
                else None,
                "avg_final_tokens": round(bucket["_final"] / bucket["completed_count"], 1)
                if bucket["completed_count"]
                else None,
                "total_summary_calls": bucket["_summary_calls"],
                "total_cache_hits": bucket["_cache_hits"],
                "total_agent_calls": bucket["_agent_calls"],
            }
        )
    rows.sort(key=lambda row: (str(row["algorithm_version"]), row["build_count"]), reverse=True)
    return rows


def cost_benefit(builds: list[dict[str, Any]]) -> dict[str, Any]:
    """Token 节省与生成成本同屏(需求 §19:不能只展示窗口变小隐藏成本)。

    - savings_tokens = Σ(原始历史 - 最终历史),只为 COMPLETED 构建累计;
    - generation_cost_calls = Σ 摘要调用(压缩 LLM 调用次数);
    - agent 调用单独列示,不与压缩成本合并;
    - savings_per_call 为除法结果,无调用时为 None。
    """

    completed = [row for row in builds if str(row.get("status") or "") == "COMPLETED"]
    savings = 0.0
    summary_calls = 0
    segment_calls = 0
    agent_calls = 0
    for row in completed:
        budget = row.get("budget") if isinstance(row.get("budget"), dict) else {}
        usage = row.get("llm_usage") if isinstance(row.get("llm_usage"), dict) else {}
        savings += _num(budget.get("history_input_tokens")) - _num(budget.get("final_context_tokens"))
        summary_calls += int(_num(usage.get("summary_calls")))
        segment_calls += int(_num(usage.get("segment_model_calls")))
        agent_calls += int(_num(usage.get("agent_calls")))
    generation_calls = summary_calls + segment_calls
    return {
        "completed_builds": len(completed),
        "token_savings": int(savings),
        "generation_llm_calls": generation_calls,
        "generation_breakdown": {"summary_calls": summary_calls, "segment_model_calls": segment_calls},
        "token_savings_per_generation_call": round(savings / generation_calls, 1) if generation_calls else None,
        "agent_llm_calls": agent_calls,
        "note": "Agent 调用是执行成本,与压缩生成成本分开列示" if agent_calls else "",
    }


def compression_agent_correlation(builds: list[dict[str, Any]]) -> dict[str, Any]:
    """压缩率与 Agent 表现的皮尔逊相关(样本不足返回 None,不硬算)。"""

    pairs: list[tuple[float, float]] = []
    for row in builds:
        budget = row.get("budget") if isinstance(row.get("budget"), dict) else {}
        agent = row.get("agent_run") if isinstance(row.get("agent_run"), dict) else {}
        if not agent or str(agent.get("status") or "") != "COMPLETED":
            continue
        raw = _num(budget.get("history_input_tokens"))
        final = _num(budget.get("final_context_tokens"))
        if raw <= 0:
            continue
        steps = agent.get("steps")
        if steps is None:
            continue
        pairs.append((1 - final / raw, float(steps)))
    if len(pairs) < MIN_CORRELATION_SAMPLES:
        return {
            "metric": "compression_rate_vs_agent_steps",
            "sample_count": len(pairs),
            "min_samples": MIN_CORRELATION_SAMPLES,
            "correlation": None,
            "note": "样本不足,暂不计算相关性" if pairs else "还没有带 Agent 运行的完成构建",
        }
    mean_x = sum(x for x, _y in pairs) / len(pairs)
    mean_y = sum(y for _x, y in pairs) / len(pairs)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator_x = math.sqrt(sum((x - mean_x) ** 2 for x, _y in pairs))
    denominator_y = math.sqrt(sum((y - mean_y) ** 2 for _x, y in pairs))
    if denominator_x == 0 or denominator_y == 0:
        return {
            "metric": "compression_rate_vs_agent_steps",
            "sample_count": len(pairs),
            "min_samples": MIN_CORRELATION_SAMPLES,
            "correlation": None,
            "note": "方差为 0,无法计算相关性",
        }
    return {
        "metric": "compression_rate_vs_agent_steps",
        "sample_count": len(pairs),
        "min_samples": MIN_CORRELATION_SAMPLES,
        "correlation": round(numerator / (denominator_x * denominator_y), 4),
        "note": "",
    }


# ── 编排:一次分析运行(采样 → 评审 → 落库 → 报告) ──


@dataclass
class AnalysisRunOutcome:
    """一次分析运行的结果(调用方据此写终态与审计)。"""

    run_id: str
    status: str
    sampled: int = 0
    judge_calls: int = 0
    judge_errors: int = 0
    report: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


def run_analysis(
    data: DataClient,
    judge: SegmentQualityJudge,
    *,
    settings: AnalysisSettings | None = None,
    trigger: str = "SCHEDULED",
) -> AnalysisRunOutcome:
    """执行一轮完整分析;任何数据服务故障收敛为 FAILED 运行,不抛出。

    页面永远只读持久化结果——本函数是唯一触发评审 LLM 调用的入口,
    仅由调度器与运维手动触发端点调用。
    """

    selected = settings or AnalysisSettings.from_env()
    try:
        run_id = data.start_context_analysis_run(trigger)
    except DataServiceError as exc:
        return AnalysisRunOutcome(run_id="", status="FAILED", error_code=f"DATA_SERVICE_ERROR:{exc.status_code or ''}")
    sampled = 0
    judge_calls = 0
    judge_errors = 0
    report: dict[str, Any] = {}
    error_code: str | None = None
    try:
        segments = data.list_recent_context_segments(limit=selected.sample_size)
        worst = "PASS"
        verdict_counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "ERROR": 0}
        for segment in segments:
            verdict = judge.judge(
                summary=str(segment.get("summaryContent") or ""),
                source_text="\n".join(str(row) for row in _source_contents(segment)),
            )
            sampled += 1
            if verdict.verdict == "ERROR":
                judge_errors += 1
            else:
                judge_calls += 1
            verdict_counts[verdict.verdict] = verdict_counts.get(verdict.verdict, 0) + 1
            worst = worst if _VERDICT_RANK.get(worst, 3) >= _VERDICT_RANK.get(verdict.verdict, 3) else verdict.verdict
            try:
                data.save_context_quality_check(
                    {
                        "accountId": segment.get("accountId"),
                        "segmentId": segment.get("segmentId"),
                        "sessionId": segment.get("sessionId"),
                        "verdict": verdict.verdict,
                        "missingFacts": list(verdict.missing_facts),
                        "hallucinations": list(verdict.hallucinations),
                        "judgeModel": None,
                        "promptVersion": SEGMENT_JUDGE_PROMPT_VERSION,
                        "sourceHashAtCheck": segment.get("sourceHash") or "",
                        "errorCode": verdict.error_code,
                        "detail": {"note": verdict.note, "duration_ms": verdict.duration_ms},
                    }
                )
            except DataServiceError:
                judge_errors += 1  # 落库失败同样计入错误,不静默丢失
        builds_payload = data.list_context_builds_cross_owner(200, 0)
        builds = [
            _with_parsed_json(row)
            for row in builds_payload.get("builds") or []
        ]
        report = {
            "quality_sampling": {
                "sampled": sampled,
                "verdict_counts": verdict_counts,
                "worst_verdict": worst if sampled else None,
            },
            "threshold_groups": threshold_groups(builds),
            "cost_benefit": cost_benefit(builds),
            "correlation": compression_agent_correlation(builds),
        }
        if judge_errors and not judge_calls:
            error_code = "JUDGE_ALL_FAILED"
            status = "FAILED"
        else:
            status = "COMPLETED"
    except DataServiceError as exc:
        status = "FAILED"
        error_code = f"DATA_SERVICE_ERROR:{exc.status_code or ''}"
    except Exception as exc:  # noqa: BLE001 —— 运行失败冻结终态,不中断服务
        status = "FAILED"
        error_code = type(exc).__name__
    if run_id:
        with contextlib.suppress(DataServiceError):  # 终态落库失败不重试;下一轮运行仍会记录
            data.finish_context_analysis_run(
                run_id,
                {
                    "status": status,
                    "sampledSegments": sampled,
                    "judgeCalls": judge_calls,
                    "judgeErrors": judge_errors,
                    "report": report,
                    "errorCode": error_code,
                },
            )
    return AnalysisRunOutcome(
        run_id=run_id,
        status=status,
        sampled=sampled,
        judge_calls=judge_calls,
        judge_errors=judge_errors,
        report=report,
        error_code=error_code,
    )


def _source_contents(segment: dict[str, Any]) -> list[str]:
    raw = segment.get("sourceContents")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return [raw]
    if isinstance(raw, list):
        return [str(row) for row in raw]
    return []


def _with_parsed_json(row: dict[str, Any]) -> dict[str, Any]:
    parsed = dict(row)
    for key in ("config_snapshot", "llm_usage", "budget", "agent_run", "item_counts"):
        value = parsed.get(key)
        if isinstance(value, str):
            try:
                parsed[key] = json.loads(value)
            except json.JSONDecodeError:
                parsed[key] = {}
    return parsed
