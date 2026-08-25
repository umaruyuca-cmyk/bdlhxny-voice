"""对比用例的三种 Agent 生产执行器与冻结 Mock 工具执行。

- Mock 返回按 match_mode(subset/exact) 匹配稳定数据;
- 写工具只返回「需要确认」或模拟结果,不产生任何外部副作用;
- 工具定义来自冻结目录快照,不构造空 Schema;
- 最终回答始终由真实 LLM 产生,本模块不 Mock 答案。
"""

from __future__ import annotations

import time
from typing import Any

from bdlh_runtime.experiments.fixture_hash import ALLOWED_MOCK_STATUSES, catalog_schema_hash
from bdlh_runtime.experiments.tool_catalog_snapshot import (
    COMPARISON_TOOL_CATALOG_VERSION,
    ComparisonToolCatalogError,
    build_comparison_catalog,
    tool_manifests,
)


class FrozenFixtureExecutor:
    """按 (工具名, match_mode, 匹配参数) 命中冻结返回;未命中返回 NOT_IN_FIXTURE。"""

    def __init__(self, fixtures: list[dict[str, Any]], *, fixture_version: str | int = 1):
        self._fixtures = list(fixtures or [])
        self._fixture_version = fixture_version
        self.call_records: list[dict[str, Any]] = []

    @staticmethod
    def _matches(fixture: dict[str, Any], arguments: dict[str, Any]) -> bool:
        expected = dict(fixture.get("match_arguments") or {})
        mode = str(fixture.get("match_mode") or "subset")
        if mode == "exact":
            return dict(arguments) == expected
        return all(arguments.get(key) == value for key, value in expected.items())

    async def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        record: dict[str, Any] = {"tool": name, "arguments": dict(arguments)}
        matched = None
        for fixture in self._fixtures:
            tool_name = str(fixture.get("tool") or fixture.get("tool_name") or "")
            if tool_name != name:
                continue
            if self._matches(fixture, arguments):
                matched = fixture
                break
        if matched is None:
            payload = {
                "status": "error",
                "error_code": "NOT_IN_FIXTURE",
                "message": f"工具 {name} 的该组参数没有冻结返回",
                "simulated": True,
            }
        else:
            status = str(matched.get("status") or "success")
            if status not in ALLOWED_MOCK_STATUSES:
                status = "error"
            raw_result = matched.get("result")
            if isinstance(raw_result, dict):
                payload = dict(raw_result)
            else:
                payload = {"value": raw_result}
            payload["status"] = status
            payload["simulated"] = True
            if matched.get("fixture_id"):
                payload["fixture_id"] = str(matched["fixture_id"])
            payload["fixture_version"] = matched.get("fixture_version", self._fixture_version)
        record["status"] = str(payload.get("status") or "success")
        record["result"] = payload
        if payload.get("fixture_id"):
            record["fixture_id"] = payload["fixture_id"]
        if "fixture_version" in payload:
            record["fixture_version"] = payload["fixture_version"]
        self.call_records.append(record)
        return payload


def comparison_tool_catalog(
    visible_tools: tuple[str, ...] | list[str],
    descriptions: dict[str, str] | None = None,
):
    """对比用例的工具目录:固定顺序 = 用例定义的标准工具范围顺序。

    从冻结快照读取真实 Schema;缺工具抛 ComparisonToolCatalogError。
    ``descriptions`` 仅用于测试覆盖,生产路径不依赖占位描述。
    """
    catalog, ordered = build_comparison_catalog(tuple(visible_tools))
    if descriptions:
        for card in ordered:
            override = descriptions.get(card.name)
            if override:
                card.description = override
    return catalog, ordered


async def run_comparison_agent(
    *,
    case: Any,
    agent_mode_id: str,
    visible_tools: tuple[str, ...] | list[str],
    max_agent_steps: int,
    llm: Any = None,
) -> dict[str, Any]:
    """三种 Agent 实现的统一执行入口(生产路径;测试可整体注入替身)。"""
    import asyncio

    from bdlh_runtime.context.token_count import ConservativeTokenCounter
    from bdlh_runtime.engine.loop import AgentLoop, AgentTurn, _tool_schema_tokens
    from bdlh_runtime.evaluation.ab_eval import build_llm_from_env
    from bdlh_runtime.evaluation.baseline_agent import naive_run
    from bdlh_runtime.evaluation.baseline_langgraph import react_official_run

    model_llm = llm or build_llm_from_env()
    conditions = dict(getattr(case, "conditions", None) or {})
    descriptions = conditions.get("tool_descriptions") or {}
    fixtures = list(conditions.get("mock_fixtures") or [])
    fixture_version = conditions.get("fixture_version") or 1
    executor = FrozenFixtureExecutor(fixtures, fixture_version=fixture_version)

    try:
        catalog, ordered_cards = comparison_tool_catalog(visible_tools, descriptions)
    except ComparisonToolCatalogError as exc:
        return {
            "answer": "",
            "error": f"CONFIG_INVALID:{exc}",
            "tool_calls": [],
            "stop_reason": "CONFIG_INVALID",
            "actual_agent_steps": 0,
            "duration_ms": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "tool_catalog_version": COMPARISON_TOOL_CATALOG_VERSION,
            "tool_catalog_hash": "",
            "validity": "INVALID",
        }

    manifests = tool_manifests(ordered_cards)
    tool_hash = catalog_schema_hash(manifests)
    counter = ConservativeTokenCounter()
    schema_tokens = _tool_schema_tokens(ordered_cards, counter)
    system_prompt = str(conditions.get("system_prompt") or "你是助理,只使用提供的冻结 Mock 工具,不编造结果。")
    started = time.perf_counter()
    stop_reason = ""
    actual_steps = 0
    tokens_in = 0
    error = None
    answer = ""
    try:
        if agent_mode_id == "full-system":
            turn = AgentTurn(
                user_id=str(conditions.get("user_id") or "comparison-user"),
                message=case.message,
                scene_tag=str(conditions.get("scene_tag") or "general"),
                authenticated=bool(conditions.get("authenticated", False)),
                run_id=f"{case.case_id}:{agent_mode_id}",
                token_budget=int(conditions.get("token_budget") or 0),
            )
            loop = AgentLoop(
                llm=model_llm,
                catalog=catalog,
                executor=executor,
                tool_loading="scoped",
                max_agent_steps=max_agent_steps,
                visible_override=frozenset(visible_tools),
            )
            result = await asyncio.wait_for(loop.run(turn), timeout=float(conditions.get("timeout_s") or 300))
            answer = result.answer
            error = result.context_error if result.degraded else None
            stop_reason = result.stop_reason or ""
            actual_steps = result.actual_steps
            tokens_in = sum(counter.count(str(getattr(m, "content", "") or "")) for m in result.messages)
        elif agent_mode_id in ("baseline-tool-calling", "langgraph-react"):
            common = dict(
                message=case.message,
                history=[],
                all_cards=ordered_cards,
                llm=model_llm,
                executor=executor,
                system_prompt=system_prompt,
            )
            if agent_mode_id == "baseline-tool-calling":
                baseline = await asyncio.wait_for(
                    naive_run(max_rounds=max_agent_steps, **common),
                    timeout=float(conditions.get("timeout_s") or 300),
                )
            else:
                baseline = await asyncio.wait_for(
                    react_official_run(**common), timeout=float(conditions.get("timeout_s") or 300)
                )
            answer = baseline.answer
            error = baseline.error
            stop_reason = "FINAL_ANSWER" if not error else "AGENT_ERROR"
            actual_steps = int(getattr(baseline, "rounds", 0) or 0)
            tokens_in = counter.count(system_prompt) + counter.count(case.message)
        else:
            raise ValueError(f"未知 Agent 实现编号:{agent_mode_id!r}")
    except TimeoutError:
        answer, error, stop_reason = "", "运行超时:单运行熔断", "TIMEOUT"
    except Exception as exc:  # noqa: BLE001 —— 单运行异常降级为一次失败运行
        answer, error, stop_reason = "", f"{type(exc).__name__}: {exc}", "AGENT_ERROR"

    return {
        "answer": answer,
        "error": error,
        "tool_calls": executor.call_records,
        "stop_reason": stop_reason,
        "actual_agent_steps": actual_steps,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "tokens_in": tokens_in + schema_tokens,
        "tokens_out": counter.count(str(answer or "")),
        "tool_catalog_version": COMPARISON_TOOL_CATALOG_VERSION,
        "tool_catalog_hash": tool_hash,
        "tool_definitions_summary": [
            {"name": card.name, "required": list((card.parameters or {}).get("required") or [])}
            for card in ordered_cards
        ],
    }
