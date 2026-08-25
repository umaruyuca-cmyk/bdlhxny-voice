"""双模式 eval 跑批（设计文档 §11.2）。

同一题库对 ``scoped`` 与 ``search`` 各跑一遍。默认离线 Fake 驱动；设置
``BDLH_EVAL_LIVE_LLM=1`` 且配置 API Key 时追加真实 LLM 标注（失败则跳过）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage

from bdlh_runtime.engine.loop import AgentLoop, AgentTurn
from bdlh_runtime.registry import load_and_validate
from bdlh_runtime.tools.catalog import ToolCatalog, catalog_from_snapshot
from bdlh_runtime.tools.search import SEARCH_TOOLS_NAME
from tests.eval.routing_cases import (
    BASELINE_TASK_SUCCESS,
    CATEGORIES,
    ROUTING_CASES,
    EvalCase,
)
from tests.helpers_encoder import LexicalEncoder
from tests.registry.seeded_store import build_seeded_store

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPORT_NAME = f"{date.today().strftime('%Y%m%d')}_装载模式对照.md"
_CHITCHAT_CANNED = "你好，我可以帮你完成已启用的任务。直接说你想做什么就行。"
_FORBIDDEN_CANNED = "这个请求超出当前允许的操作范围，我不能执行写入、资金划转或绕过系统指令。"


@dataclass
class CaseOutcome:
    case_id: str
    category: str
    success: bool
    rounds: int
    approx_tokens: int
    retrieval_applicable: bool
    retrieval_hit: bool | None
    reason: str = ""


@dataclass
class ModeSummary:
    tool_loading: str
    outcomes: list[CaseOutcome] = field(default_factory=list)

    @property
    def task_success_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(1 for item in self.outcomes if item.success) / len(self.outcomes)

    @property
    def retrieval_hit_rate(self) -> float | None:
        applicable = [item for item in self.outcomes if item.retrieval_applicable]
        if not applicable:
            return None
        return sum(1 for item in applicable if item.retrieval_hit) / len(applicable)

    @property
    def mean_rounds(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(item.rounds for item in self.outcomes) / len(self.outcomes)

    @property
    def mean_approx_tokens(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(item.approx_tokens for item in self.outcomes) / len(self.outcomes)

    def by_category(self) -> dict[str, float]:
        grouped: dict[str, list[CaseOutcome]] = {name: [] for name in CATEGORIES}
        for item in self.outcomes:
            grouped.setdefault(item.category, []).append(item)
        return {
            name: (sum(1 for item in rows if item.success) / len(rows) if rows else 0.0)
            for name, rows in grouped.items()
        }


@dataclass
class DualModeReport:
    scoped: ModeSummary
    search: ModeSummary
    live_note: str
    case_count: int


class LabeledRouter:
    """按金标分流；不走真实 embedding，保证对照测的是装载策略。"""

    def __init__(self, case: EvalCase) -> None:
        self._case = case

    def route(self, _message: str) -> Any:
        if not self._case.fastpath:
            return None
        canned = None
        if self._case.fastpath == "chitchat":
            canned = _CHITCHAT_CANNED
        elif self._case.fastpath == "forbidden":
            canned = _FORBIDDEN_CANNED
        return SimpleNamespace(name=self._case.fastpath, response=canned)


class ScriptedChatModel:
    """按金标发起 search_tools / 业务工具；绑定集合决定 search 是否可达。"""

    def __init__(self, case: EvalCase) -> None:
        self._case = case
        self.bind_history: list[list[Any]] = []
        self.invoke_count = 0
        self.schema_chars = 0
        self.message_chars = 0
        self._search_done = False
        self._called: set[str] = set()
        self._probed = False

    def bind_tools(self, tools: list[Any], **_kwargs: Any) -> ScriptedChatModel:
        snapshot = list(tools)
        self.bind_history.append(snapshot)
        self.schema_chars += sum(len(json.dumps(item, ensure_ascii=False, default=str)) for item in snapshot)
        return self

    async def ainvoke(self, messages: list[Any], **_kwargs: Any) -> AIMessage:
        self.invoke_count += 1
        self.message_chars += _messages_chars(messages)
        bound = _bound_names(self.bind_history[-1] if self.bind_history else [])
        needs_search = bool(self._case.expected_tools or self._case.search_query or self._case.probe_tool)
        if SEARCH_TOOLS_NAME in bound and not self._search_done and needs_search:
            self._search_done = True
            query = self._case.search_query or self._case.message
            return _tool_message(SEARCH_TOOLS_NAME, {"query": query}, "search")
        for name in self._case.expected_tools:
            if name in bound and name not in self._called:
                self._called.add(name)
                return _tool_message(name, self._case.tool_arguments.get(name, {}), name)
        if self._case.probe_tool and not self._probed:
            self._probed = True
            return _tool_message(self._case.probe_tool, {}, "probe")
        return AIMessage(content=self._case.final_answer)


async def _echo(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"tool": name, "args": arguments}


def _bound_names(tools: list[Any]) -> set[str]:
    names: set[str] = set()
    for spec in tools:
        if isinstance(spec, dict):
            function = spec.get("function") if isinstance(spec.get("function"), dict) else spec
            name = function.get("name") if isinstance(function, dict) else None
            if name:
                names.add(str(name))
    return names


def _tool_message(name: str, arguments: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": arguments, "id": call_id, "type": "tool_call"}],
    )


def _messages_chars(messages: list[Any]) -> int:
    total = 0
    for message in messages:
        content = getattr(message, "content", "") or ""
        if isinstance(content, str):
            total += len(content)
        else:
            total += len(json.dumps(content, ensure_ascii=False, default=str))
    return total


def _approx_tokens(model: ScriptedChatModel) -> int:
    return max(0, (model.message_chars + model.schema_chars + 3) // 4)


def _judge(case: EvalCase, result: Any, *, tool_loading: str) -> tuple[bool, bool | None, str]:
    if case.fastpath:
        ok = result.fastpath_name == case.fastpath and result.entered_loop is False
        return ok, None, "" if ok else f"fastpath={result.fastpath_name}"
    success_names = {audit.tool_name for audit in result.audits if audit.status == "SUCCESS"}
    missing = [name for name in case.expected_tools if name not in success_names]
    leaked = [name for name in case.absent_tools if name in success_names]
    retrieval_hit: bool | None = None
    if tool_loading == "search" and (case.expected_tools or case.probe_tool or case.search_query) and not case.fastpath:
        retrieval_hit = _search_hit(result, case)
    if missing:
        return False, retrieval_hit, f"missing={missing}"
    if leaked:
        return False, retrieval_hit, f"leaked={leaked}"
    return True, retrieval_hit, ""


def _search_hit(result: Any, case: EvalCase) -> bool:
    names: set[str] = set()
    for message in result.messages:
        content = getattr(message, "content", "") or ""
        if not isinstance(content, str) or "names" not in content:
            continue
        try:
            body = json.loads(content)
        except json.JSONDecodeError:
            continue
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict) and isinstance(data.get("names"), list):
            names.update(str(item) for item in data["names"])
    if case.absent_tools:
        return not any(name in names for name in case.absent_tools)
    if not case.expected_tools:
        return True
    return any(name in names for name in case.expected_tools)


async def run_case(catalog: ToolCatalog, case: EvalCase, *, tool_loading: str) -> CaseOutcome:
    llm = ScriptedChatModel(case)
    loop = AgentLoop(
        llm=llm,
        catalog=catalog,
        executor=_echo,
        router=LabeledRouter(case),
        tool_loading=tool_loading,
        encoder=LexicalEncoder() if tool_loading == "search" else None,
        max_tool_calls=8,
    )
    result = await loop.run(
        AgentTurn(
            user_id="eval-user" if case.authenticated else "guest",
            message=case.message,
            scene_tag=case.scene_tag,
            authenticated=case.authenticated,
            history=list(case.history),
            run_id=f"eval-{case.id}-{tool_loading}",
        )
    )
    success, retrieval_hit, reason = _judge(case, result, tool_loading=tool_loading)
    applicable = retrieval_hit is not None
    return CaseOutcome(
        case_id=case.id,
        category=case.category,
        success=success,
        rounds=llm.invoke_count,
        approx_tokens=_approx_tokens(llm),
        retrieval_applicable=applicable,
        retrieval_hit=retrieval_hit,
        reason=reason,
    )


async def run_mode(catalog: ToolCatalog, *, tool_loading: str) -> ModeSummary:
    summary = ModeSummary(tool_loading=tool_loading)
    for case in ROUTING_CASES:
        summary.outcomes.append(await run_case(catalog, case, tool_loading=tool_loading))
    return summary


def _live_note() -> str:
    flag = os.getenv("BDLH_EVAL_LIVE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}
    if not flag:
        return "未开启 BDLH_EVAL_LIVE_LLM，跳过真实 LLM 标注。"
    from bdlh_runtime.infra.llm import create_llm

    llm = create_llm(api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY"))
    if llm is None:
        return "已开启 BDLH_EVAL_LIVE_LLM 但无 API Key / 客户端，跳过真实 LLM 标注。"
    return "真实 LLM 客户端可用；本报告仍以 Fake 金标对照为准（避免非确定性污染选型）。"


async def run_dual_mode_eval(catalog: ToolCatalog | None = None) -> DualModeReport:
    if catalog is None:
        catalog = catalog_from_snapshot(load_and_validate(build_seeded_store()))
    scoped = await run_mode(catalog, tool_loading="scoped")
    search = await run_mode(catalog, tool_loading="search")
    return DualModeReport(
        scoped=scoped,
        search=search,
        live_note=_live_note(),
        case_count=len(ROUTING_CASES),
    )


def report_to_dict(report: DualModeReport) -> dict[str, Any]:
    def _mode(summary: ModeSummary) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool_loading": summary.tool_loading,
            "task_success_rate": round(summary.task_success_rate, 4),
            "mean_rounds": round(summary.mean_rounds, 4),
            "mean_approx_tokens": round(summary.mean_approx_tokens, 2),
            "by_category": {name: round(rate, 4) for name, rate in summary.by_category().items()},
            "failures": [
                {"id": item.case_id, "reason": item.reason} for item in summary.outcomes if not item.success
            ],
        }
        if summary.retrieval_hit_rate is not None:
            payload["retrieval_hit_rate"] = round(summary.retrieval_hit_rate, 4)
        else:
            payload["retrieval_hit_rate"] = None
        return payload

    return {
        "case_count": report.case_count,
        "baseline_task_success": BASELINE_TASK_SUCCESS,
        "live_note": report.live_note,
        "scoped": _mode(report.scoped),
        "search": _mode(report.search),
    }


def render_markdown(report: DualModeReport) -> str:
    data = report_to_dict(report)
    scoped = data["scoped"]
    search = data["search"]
    rec = _recommendation(report)
    scoped_row = (
        f"| scoped | {_pct(scoped['task_success_rate'])} | — | "
        f"{scoped['mean_rounds']:.2f} | {scoped['mean_approx_tokens']:.0f} |"
    )
    search_row = (
        f"| search | {_pct(search['task_success_rate'])} | "
        f"{_pct(search['retrieval_hit_rate'])} | {search['mean_rounds']:.2f} | "
        f"{search['mean_approx_tokens']:.0f} |"
    )
    lines = [
        f"# 装载模式对照（{date.today().isoformat()}）",
        "",
        "设计文档 §11.2：同一题库对 `scoped` 与 `search` 对照任务成功率、检索命中率、平均轮次、token 消耗。",
        "",
        f"- 题库：{data['case_count']} 条（闲聊 / 知识 / 金融研究 / 组合 / 适合度 / 多轮指代 / 误伤 / 看护 各 ≥6）",
        "- 驱动：离线 Fake 金标（ScriptedChatModel + LabeledRouter）",
        f"- 题库基线（任务成功率）：{BASELINE_TASK_SUCCESS:.0%}",
        f"- {data['live_note']}",
        "- token：消息字符 + `bind_tools` schema 字符，按 4 字符 ≈ 1 token 近似",
        "",
        "## 总表",
        "",
        "| 策略 | 任务成功率 | 检索命中率 | 平均轮次 | 平均近似 token |",
        "|---|---:|---:|---:|---:|",
        scoped_row,
        search_row,
        "",
        "## 分场景任务成功率",
        "",
        "| 场景 | scoped | search |",
        "|---|---:|---:|",
    ]
    for name in CATEGORIES:
        lines.append(
            f"| {name} | {_pct(scoped['by_category'].get(name, 0))} | {_pct(search['by_category'].get(name, 0))} |"
        )
    if scoped["failures"] or search["failures"]:
        lines.extend(["", "## 失败题", ""])
        for label, rows in (("scoped", scoped["failures"]), ("search", search["failures"])):
            if not rows:
                continue
            lines.append(f"### {label}")
            for row in rows:
                lines.append(f"- `{row['id']}`：{row['reason']}")
    lines.extend(
        [
            "",
            "## 结论与默认策略建议",
            "",
            rec,
            "",
            "## 口径",
            "",
            "- 任务成功：快路径金标命中，或期望工具 `SUCCESS` 且 `absent_tools` 未成功。",
            "- search 检索命中：`search_tools` Observation 的 `names` 含期望工具；"
            "误伤游客持仓题则要求 `names` 不含持仓工具（权限过滤先于检索）。",
            "- Fake 不评估真实模型选工具质量；该项留给可选真实 LLM 标注。",
            "",
        ]
    )
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0%}"


def _recommendation(report: DualModeReport) -> str:
    scoped_ok = report.scoped.task_success_rate >= BASELINE_TASK_SUCCESS
    search_ok = report.search.task_success_rate >= BASELINE_TASK_SUCCESS
    if not scoped_ok or not search_ok:
        return (
            f"有模式低于题库基线（scoped={report.scoped.task_success_rate:.0%}，"
            f"search={report.search.task_success_rate:.0%}），不得据此切换默认策略，需先修装载可达性。"
        )
    rounds_delta = report.search.mean_rounds - report.scoped.mean_rounds
    token_delta = report.search.mean_approx_tokens - report.scoped.mean_approx_tokens
    hit = report.search.retrieval_hit_rate
    hit_text = "—" if hit is None else f"{hit:.0%}"
    return (
        f"两种策略任务成功率均达到基线。search 平均多 {rounds_delta:.2f} 轮（检索节点），"
        f"近似 token 差 {token_delta:.0f}（search−scoped），检索命中率 {hit_text}。"
        "当前工具规模约二十张 ToolCard，scoped 更确定、可审计；search 面向规模增长。"
        "建议保持默认 `tool_loading=scoped`，search 继续作为实验策略（设计文档 D-4）。"
    )


def write_report(report: DualModeReport, path: Path | None = None) -> Path:
    target = path or (_REPO_ROOT / "docs" / "eval" / _REPORT_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(report), encoding="utf-8")
    return target


def below_baseline(report: DualModeReport) -> list[str]:
    bad: list[str] = []
    if report.scoped.task_success_rate < BASELINE_TASK_SUCCESS:
        bad.append("scoped")
    if report.search.task_success_rate < BASELINE_TASK_SUCCESS:
        bad.append("search")
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="scoped vs search eval")
    parser.add_argument("--write-report", action="store_true", default=True)
    parser.add_argument("--no-write-report", action="store_true")
    args = parser.parse_args(argv)
    report = asyncio.run(run_dual_mode_eval())
    payload = report_to_dict(report)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.write_report and not args.no_write_report:
        path = write_report(report)
        print(f"report={path}")
    failed = below_baseline(report)
    if failed:
        print(f"below_baseline={failed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
