"""冻结来源上的上下文工作台构建服务。"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import UTC, datetime
from typing import Any

from bdlh_runtime.context import TokenCounter, counter_from_env
from bdlh_runtime.engine.loop import load_prompt
from bdlh_runtime.session import SegmentUsage, SessionCompiler, serialize_session
from bdlh_runtime.session.llm_summary import summary_call_cap
from bdlh_runtime.session.loader import SessionCase, SessionEvent, canonical_json_hash

from .agent_run import (
    AGENT_RUN_STATUS_ACTIVE,
    AgentRunInvalid,
    AgentRunner,
    ToolLoopAgentRunner,
)
from .segments import (
    MemorySegmentManager,
    MemorySegmentRepository,
    MemorySegmentStoreError,
    SegmentPreparation,
    SegmentSettings,
)
from .sources import FrozenSessionSource, SessionSource
from .store import ContextBuildStore
from .turns import events_with_turns


class CurrentRequestNotFound(LookupError):
    """当前请求事件不存在。"""


class CurrentRequestInvalid(ValueError):
    """当前请求事件不是用户消息。"""


class ContextWorkbenchService:
    """工作台用例读取与 ``budgeted-hybrid-v1`` 构建。"""

    def __init__(
        self,
        store: ContextBuildStore,
        source: SessionSource | None = None,
        *,
        segment_repository: MemorySegmentRepository | None = None,
        segment_summarizer: Any | None = None,
        segment_counter: TokenCounter | None = None,
        agent_runner: AgentRunner | None = None,
    ) -> None:
        self.store = store
        self.source = source or FrozenSessionSource()
        #: Segment 仓库(incremental/shadow 装配;legacy/默认为 None → 行为与旧版一致)
        self.segment_repository = segment_repository
        self._segment_summarizer = segment_summarizer
        self._segment_counter = segment_counter
        #: Agent 运行器(P1;默认惰性创建真实 LLM 运行器,单测注入假实现)
        self._agent_runner = agent_runner

    @property
    def agent_runner(self) -> AgentRunner:
        if self._agent_runner is None:
            # 默认经统一原生 Tool Calling 底座执行(多轮工具调用);
            # 单测或显式回退注入 run() 契约的假实现/单次调用运行器
            self._agent_runner = ToolLoopAgentRunner()
        return self._agent_runner

    def sessions(self) -> list[dict[str, Any]]:
        return self.source.list_sessions()

    def overview(self, session_id: str, owner_id: str | None = None) -> dict[str, Any]:
        session, _variants = self.source.get_session(session_id)
        turned = events_with_turns(session.events)
        current = self._default_request(session.events)
        turn_count = len({row["turn_id"] for row in turned if row["turn_id"] != "turn-0000"})
        # 记忆状态(§7.1):legacy 未装配 Segment 仓库时为 None,页面显示"—"不补零
        frozen_segment_count: int | None = None
        recent_raw_turns: int | None = None
        if self.segment_repository is not None:
            try:
                frozen_segment_count = len(self.segments(session_id)["segments"])
            except MemorySegmentStoreError:
                frozen_segment_count = None  # 仓库故障不阻塞概览,计数显示"—"
            recent_raw_turns = min(SegmentSettings.from_env().recent_raw_turns, turn_count)
        latest_build = self.store.latest_for_session(owner_id, session_id) if owner_id else None
        return {
            "session_id": session.session_id,
            "title": session.title,
            "source_type": self.source.source_type,
            "source_version": session.session_version,
            "source_hash": session.source_hash,
            "event_count": len(session.events),
            "turn_count": turn_count,
            "user_message_count": sum(1 for event in session.events if event.type == "user_message"),
            "tool_pair_count": sum(1 for event in session.events if event.type == "tool_call"),
            "default_current_request_event_id": current.event_id,
            "current_request_candidates": [
                {
                    "event_id": event.event_id,
                    "occurred_at": event.occurred_at,
                    "excerpt": event.content[:160],
                }
                for event in session.events
                if event.type == "user_message"
            ],
            "algorithm_version": "budgeted-hybrid-v1",
            "frozen_segment_count": frozen_segment_count,
            "recent_raw_turns": recent_raw_turns,
            "latest_build": latest_build,
        }

    def segments(self, session_id: str) -> dict[str, Any]:
        """会话级冻结 Segment 摘要库(§12/§16);只返回安全展示字段。

        legacy 未装配仓库时 ``enabled=False`` 且列表为空;仓库故障向上抛
        ``MemorySegmentStoreError``,由 API 层映射稳定错误码。
        """

        if self.segment_repository is None:
            return {"session_id": session_id, "enabled": False, "segments": []}
        rows = self.segment_repository.list_segments(self.segment_owner_id, session_id)
        return {
            "session_id": session_id,
            "enabled": True,
            "segments": [self._segment_library_row(segment) for segment in rows],
        }

    @property
    def segment_owner_id(self) -> str:
        """Segment 仓库绑定的所有者(DataService 仓库构造时固化)。"""

        owner = getattr(self.segment_repository, "owner_id", None)
        return str(owner) if owner else ""

    @staticmethod
    def _segment_library_row(segment: Any) -> dict[str, Any]:
        return {
            "segment_id": segment.segment_id,
            "start_event_id": segment.start_event_id,
            "end_event_id": segment.end_event_id,
            "source_event_ids": list(segment.source_event_ids),
            "event_count": len(segment.source_event_ids),
            "source_hash_short": segment.source_hash[:19],
            "source_tokens": segment.source_tokens,
            "summary_tokens": segment.summary_tokens,
            "status": segment.status,
            "generation_mode": segment.generation_mode,
            "summary_model": segment.summary_model,
            "prompt_version": segment.prompt_version,
            "algorithm_version": segment.algorithm_version,
            "fallback_reason": segment.fallback_reason,
            "summary_excerpt": segment.summary_content[:600],
        }

    def events(self, session_id: str) -> list[dict[str, Any]]:
        session, _variants = self.source.get_session(session_id)
        return events_with_turns(session.events)

    def build_trends(self, session_id: str, owner_id: str, limit: int = 20) -> dict[str, Any]:
        """跨构建趋势(P2):该会话最近 N 次构建的真实计量演进。

        数据源为两种 Store 统一的跨所有者行形状(经 owner+session 过滤);
        压缩率 = 1 - 最终/原始,输入输出均为构建快照真实计数,不做估算。
        """

        payload = self.store.list_builds_cross_owner(200, 0)
        candidates = [
            row
            for row in payload.get("builds") or []
            if str(row.get("owner_id") or "") == owner_id and str(row.get("session_id") or "") == session_id
        ]
        candidates.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        rows = [self._trend_row(row) for row in candidates[: max(1, min(limit, 100))]]
        return {
            "session_id": session_id,
            "build_count": len(candidates),
            "returned": len(rows),
            "trends": rows,
        }

    @staticmethod
    def _trend_row(row: dict[str, Any]) -> dict[str, Any]:
        budget = row.get("budget") if isinstance(row.get("budget"), dict) else {}
        usage = row.get("llm_usage") if isinstance(row.get("llm_usage"), dict) else {}
        raw_tokens = int(budget.get("history_input_tokens") or 0)
        final_tokens = int(budget.get("final_context_tokens") or 0)
        compression_rate: float | None = None
        if raw_tokens > 0 and final_tokens >= 0:
            compression_rate = round(1 - final_tokens / raw_tokens, 4)
        return {
            "build_id": row.get("build_id"),
            "created_at": row.get("created_at"),
            "status": row.get("status"),
            "raw_tokens": raw_tokens,
            "final_tokens": final_tokens,
            "compression_rate": compression_rate,
            "summary_calls": int(usage.get("summary_calls") or 0),
            "cache_hits": int(usage.get("cache_hits") or 0),
            "segment_cache_hits": int(usage.get("segment_cache_hits") or 0),
            "agent_calls": int(usage.get("agent_calls") or 0),
            "agent_tool_calls": int(usage.get("agent_tool_calls") or 0),
        }

    def segment_quality(
        self,
        session_id: str,
        limit: int = 20,
        *,
        semantic_checks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """摘要质量抽检(P2):规则级实时校验 + 语义级持久化结果(如有)。

        语义评审由定时分析任务后台执行并落库(不在页面加载时调 LLM);
        ``semantic_checks`` 由 API 层读取后传入,None=暂不可用。
        """

        semantic = self._semantic_rows(semantic_checks)
        if self.segment_repository is None:
            return {
                "session_id": session_id,
                "enabled": False,
                "checked": 0,
                "passed": 0,
                "issues": [],
                "rows": [],
                "semantic": semantic,
            }
        segments = self.segment_repository.list_segments(self.segment_owner_id, session_id)
        max_tokens = SegmentSettings.from_env().max_summary_tokens
        issues: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        passed = 0
        for segment in segments[: max(1, min(limit, 100))]:
            problems: list[str] = []
            if not (segment.summary_content or "").strip():
                problems.append("EMPTY_SUMMARY")
            if not segment.source_event_ids:
                problems.append("MISSING_SOURCE_EVENTS")
            if not segment.source_hash:
                problems.append("MISSING_SOURCE_HASH")
            if segment.summary_tokens > max_tokens:
                problems.append("SUMMARY_OVER_BUDGET")
            if segment.status not in {"FROZEN", "VALIDATED"}:
                problems.append(f"STATUS_{segment.status}")
            if problems:
                issues.append({"segment_id": segment.segment_id, "problems": problems})
            else:
                passed += 1
            rows.append(
                {
                    "segment_id": segment.segment_id,
                    "start_event_id": segment.start_event_id,
                    "end_event_id": segment.end_event_id,
                    "event_count": len(segment.source_event_ids),
                    "source_tokens": segment.source_tokens,
                    "summary_tokens": segment.summary_tokens,
                    "token_ratio": round(segment.summary_tokens / segment.source_tokens, 4)
                    if segment.source_tokens > 0
                    else None,
                    "status": segment.status,
                    "generation_mode": segment.generation_mode,
                    "fallback_reason": segment.fallback_reason,
                    "problems": problems,
                }
            )
        return {
            "session_id": session_id,
            "enabled": True,
            "checked": len(rows),
            "passed": passed,
            "issues": issues,
            "rows": rows,
            "semantic": semantic,
        }

    @staticmethod
    def _semantic_rows(checks: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """语义抽检持久化行的安全展示(裁剪到 verdict/清单/时间)。"""

        if checks is None:
            return None
        rows: list[dict[str, Any]] = []
        for check in checks:
            missing = check.get("missingFacts") or check.get("missing_facts") or []
            hallucinations = check.get("hallucinations") or []
            if isinstance(missing, str):
                try:
                    missing = json.loads(missing)
                except json.JSONDecodeError:
                    missing = []
            if isinstance(hallucinations, str):
                try:
                    hallucinations = json.loads(hallucinations)
                except json.JSONDecodeError:
                    hallucinations = []
            rows.append(
                {
                    "segment_id": check.get("segmentId") or check.get("segment_id"),
                    "verdict": check.get("verdict"),
                    "missing_facts": [str(row) for row in missing],
                    "hallucinations": [str(row) for row in hallucinations],
                    "judge_model": check.get("judgeModel") or check.get("judge_model"),
                    "prompt_version": check.get("promptVersion") or check.get("prompt_version"),
                    "error_code": check.get("errorCode") or check.get("error_code"),
                    "checked_at": check.get("createdAt") or check.get("created_at"),
                }
            )
        return rows

    def create_build(
        self,
        *,
        owner_id: str,
        session_id: str,
        current_request_event_id: str,
        algorithm: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        if algorithm != "budgeted-hybrid-v1":
            raise ValueError(f"unsupported algorithm {algorithm!r}")
        session, _variants = self.source.get_session(session_id)
        self._current_request(session.events, current_request_event_id)
        return self.store.create(
            owner_id=owner_id,
            session_id=session_id,
            current_request_event_id=current_request_event_id,
            algorithm=algorithm,
            idempotency_key=idempotency_key,
            source_type=self.source.source_type,
            config_snapshot=self._threshold_snapshot(),
        )

    @staticmethod
    def _threshold_snapshot() -> dict[str, Any]:
        """构建时冻结阈值配置(P2 对照分组键);缺省值也如实记录。"""

        settings = SegmentSettings.from_env()
        return {
            "algorithm_version": "budgeted-hybrid-v1",
            "context_memory_mode": (os.getenv("CONTEXT_MEMORY_MODE", "legacy")).strip().lower(),
            "recent_raw_turns": settings.recent_raw_turns,
            "segment_max_tokens": settings.max_summary_tokens,
            "summary_call_cap": summary_call_cap(),
        }

    def execute_build(self, build_id: str, owner_id: str) -> None:
        row = self.store.get(build_id, owner_id)
        try:
            mode = (os.getenv("CONTEXT_MEMORY_MODE", "legacy")).strip().lower()
            segment_manager = self._segment_manager(owner_id, mode)
            self.store.start_phase(build_id, "LOAD_HISTORY")
            session, variants = self.source.get_session(str(row["session_id"]))
            current = self._current_request(session.events, str(row["current_request_event_id"]))
            history_events = tuple(event for event in session.events if event.seq < current.seq)
            history_session = self._history_session(session, history_events, current)
            turned = events_with_turns(session.events)
            self.store.finish_phase(build_id, "LOAD_HISTORY", "SUCCEEDED", "HISTORY_LOADED")

            self.store.start_phase(build_id, "CLASSIFY_AND_SELECT")
            serialized = serialize_session(history_session)
            classifications = {entry.item.item_id: entry.item.classification.value for entry in serialized}
            self.store.finish_phase(build_id, "CLASSIFY_AND_SELECT", "SUCCEEDED", "ITEMS_SELECTED")

            self.store.start_phase(build_id, "SUMMARIZE_HISTORY")
            # Segment 复用编排(§8):incremental 生成并保存;shadow 只观察;
            # legacy 保持现有行为,不读写 Segment。
            preparation = SegmentPreparation()
            if segment_manager is not None:
                incremental = mode == "incremental"
                preparation = segment_manager.prepare(
                    session_id=session.session_id,
                    history_events=history_events,
                    allow_generation=incremental,
                    allow_save=incremental,
                )
            variant = next(
                row for row in variants.get("context_variants") or [] if row.get("variant_id") == "budgeted-session"
            )
            hybrid_variant = dict(variant)
            hybrid_variant["variant_id"] = "budgeted-hybrid-v1"
            hybrid_variant["strategy_version"] = "budgeted-hybrid-v1"
            compiler = SessionCompiler.from_env(llm_summary=True)
            use_segments = preparation.segments if mode == "incremental" else ()
            compiled = compiler.compile(
                history_session,
                hybrid_variant,
                common_rules=load_prompt("system_base.md", "scene_chat.md"),
                history_segments=use_segments,
                segment_usage=SegmentUsage(
                    cache_hits=preparation.cache_hits,
                    generated=preparation.generated,
                    invalidated=preparation.invalidated,
                ),
            )
            summary_status, summary_code = self._summary_status(compiled, preparation)
            self.store.finish_phase(build_id, "SUMMARIZE_HISTORY", summary_status, summary_code)

            self.store.start_phase(build_id, "VALIDATE_AND_PERSIST")
            if not compiled.required_retained:
                raise RuntimeError("REQUIRED_FACT_MISSING")
            if not compiled.budget_fit:
                raise RuntimeError("SUMMARY_OVER_BUDGET")
            decisions = self._decisions(compiled, classifications)
            self.store.finish_phase(build_id, "VALIDATE_AND_PERSIST", "SUCCEEDED", "SUMMARY_FROZEN")

            self.store.start_phase(build_id, "ASSEMBLE_CONTEXT")
            counter, _version = counter_from_env()
            artifact = {
                "artifact_version": "context-workbench-v1",
                "build_id": build_id,
                "session_id": session.session_id,
                "source_type": self.source.source_type,
                "source_hash": history_session.source_hash,
                "current_request_event_id": current.event_id,
                "algorithm_version": "budgeted-hybrid-v1",
                "messages": [
                    {
                        "order": index,
                        "role": message.role,
                        # 逐消息真实 Token(需求 §11.2 Token 视图数据源)
                        "tokens": counter.count(message.content),
                        "content": message.content,
                    }
                    for index, message in enumerate(compiled.compiled_messages)
                ],
                "message_hash": compiled.compiled_context_hash,
                "working_tokens": compiled.working_tokens,
                "tokenizer_version": compiled.tokenizer_version,
                "source_event_ids": list(compiled.input_event_ids),
                "events": turned,
            }
            if segment_manager is not None:
                artifact["memory_segment_ids"] = list(compiled.memory_segment_ids)
                artifact["memory_segments"] = self._segment_rows(preparation, turned)
            current_tokens = counter.count(current.content)
            item_counts = self._item_counts(classifications, decisions)
            budget = {
                "context_budget_tokens": compiled.token_budget,
                "current_request_tokens": current_tokens,
                "history_input_tokens": compiled.original_tokens,
                "final_context_tokens": compiled.working_tokens,
                "tokenizer_version": compiled.tokenizer_version,
            }
            llm_usage: dict[str, Any] = {
                "classification_calls": 0,
                "summary_calls": compiled.build_model_calls + preparation.model_calls,
                "cache_hits": compiled.build_cache_hits,
                # 调用上限写入构建快照(需求 §10.3:可配置且必须入快照)
                "summary_call_cap": summary_call_cap(),
            }
            if segment_manager is not None:
                llm_usage.update(
                    {
                        "segment_cache_hits": preparation.cache_hits,
                        "segment_generated": preparation.generated,
                        "segment_invalidated": preparation.invalidated,
                        "segment_fallbacks": preparation.fallbacks,
                        "segment_model_calls": preparation.model_calls,
                        "segment_saved_tokens": preparation.saved_tokens,
                        "old_history_turns": preparation.old_turns,
                        "recent_raw_turns": preparation.recent_raw_turns,
                    }
                )
            self.store.finish_phase(build_id, "ASSEMBLE_CONTEXT", "SUCCEEDED", "ARTIFACT_CREATED")

            self.store.start_phase(build_id, "COMPLETED")
            self.store.finish_phase(build_id, "COMPLETED", "SUCCEEDED", "BUILD_COMPLETED")
            self.store.complete(
                build_id,
                budget=budget,
                item_counts=item_counts,
                llm_usage=llm_usage,
                warnings=[*compiled.warnings, *preparation.warnings],
                decisions=decisions,
                artifact=artifact,
            )
        except Exception as exc:  # noqa: BLE001 - 构建必须冻结失败状态，不能遗留 RUNNING
            code = str(exc) if str(exc) in {"REQUIRED_FACT_MISSING", "SUMMARY_OVER_BUDGET"} else type(exc).__name__
            self.store.fail(build_id, code, str(exc))

    def start_agent_run(self, build_id: str, owner_id: str) -> tuple[dict[str, Any], bool]:
        """运行前置校验并写入 RUNNING 快照;返回 (快照, 是否本次新启动)。

        幂等(需求 §23 P1"一次点击一次运行"):
        - 已有终态运行 → 原样返回 (snapshot, False),不再发起调用;
        - 已有活跃运行 → AgentRunConflict;
        - 构建未完成/无工件 → AgentRunInvalid。
        """

        row = self.store.get(build_id, owner_id)
        existing = row.get("agent_run")
        if existing and existing.get("status") in AGENT_RUN_STATUS_ACTIVE:
            raise AgentRunInvalid("AGENT_RUN_ALREADY_ACTIVE", "该构建已有正在执行的 Agent 运行")
        if existing:
            return dict(existing), False
        if row.get("status") != "COMPLETED":
            raise AgentRunInvalid("BUILD_NOT_COMPLETED", f"构建状态为 {row.get('status')!r},无法运行 Agent")
        if not row.get("artifact_id"):
            raise AgentRunInvalid("ARTIFACT_MISSING", "构建没有冻结工件,无法运行 Agent")

        artifact = self.store.artifact(build_id, owner_id)
        messages = [{"role": row_["role"], "content": row_["content"]} for row_ in artifact.get("messages") or []]
        if not messages:
            raise AgentRunInvalid("ARTIFACT_EMPTY", "冻结工件没有消息序列")
        snapshot: dict[str, Any] = {
            "run_id": f"ctxar-run-{build_id}",
            "status": "RUNNING",
            "artifact_id": artifact.get("artifact_id") or row.get("artifact_id"),
            "message_hash_at_run": canonical_json_hash(messages),
            "message_count": len(messages),
            "started_at": datetime.now(UTC).isoformat(),
        }
        self.store.start_agent_run(build_id, snapshot)
        return snapshot, True

    def execute_agent_run(self, build_id: str, owner_id: str) -> None:
        """执行模型调用并冻结运行终态;任何失败都收敛为 FAILED 快照,不影响构建本身。"""

        from .agent_run import classify_agent_error

        row = self.store.get(build_id, owner_id)
        snapshot = dict(row.get("agent_run") or {})
        if not snapshot or snapshot.get("status") not in AGENT_RUN_STATUS_ACTIVE:
            return
        artifact = self.store.artifact(build_id, owner_id)
        messages = [{"role": item["role"], "content": item["content"]} for item in artifact.get("messages") or []]
        sent_hash = canonical_json_hash(messages)
        try:
            if sent_hash != snapshot.get("message_hash_at_run"):
                # 运行期间工件被改动:发送内容与登记哈希不一致,判失效(需求 §11.1)
                raise AgentRunInvalid("ARTIFACT_INVALIDATED", "工件消息序列在运行期间发生变化")
            result = self._invoke_agent_runner(messages, str(row["session_id"]))
            after = self.store.artifact(build_id, owner_id)
            after_hash = canonical_json_hash(
                [{"role": item["role"], "content": item["content"]} for item in after.get("messages") or []]
            )
            if after_hash != sent_hash:
                raise AgentRunInvalid("ARTIFACT_INVALIDATED", "工件消息序列在运行期间发生变化")
        except AgentRunInvalid as exc:
            snapshot.update(
                {
                    "status": "FAILED",
                    "error_code": exc.code,
                    "error_message": str(exc),
                    "finished_at": datetime.now(UTC).isoformat(),
                }
            )
            self.store.finish_agent_run(build_id, snapshot)
            return
        except Exception as exc:  # noqa: BLE001 —— 模型失败冻结为快照终态,不中断服务
            snapshot.update(
                {
                    "status": "FAILED",
                    "error_code": classify_agent_error(exc),
                    "error_message": str(exc),
                    "finished_at": datetime.now(UTC).isoformat(),
                }
            )
            self.store.finish_agent_run(build_id, snapshot)
            return
        snapshot.update(
            {
                "status": "COMPLETED",
                "output": result.output,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "estimated": result.estimated,
                "duration_ms": result.duration_ms,
                # 工具循环口径(P1):模型往返步数、停止原因与工具调用记录
                "steps": result.steps,
                "stop_reason": result.stop_reason,
                "tool_calls": [dict(call) for call in result.tool_calls],
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        self.store.finish_agent_run(
            build_id,
            snapshot,
            llm_usage_patch={
                # Agent 调用与压缩调用分开计量(需求 §11.3/§17);
                # agent_calls = 模型往返次数(单次调用路径无步数口径时为 1)
                "agent_calls": result.steps if result.steps > 0 else 1,
                "agent_tool_calls": len(result.tool_calls),
                "agent_input_tokens": result.input_tokens,
                "agent_output_tokens": result.output_tokens,
                "agent_model": result.model,
            },
        )

    def _invoke_agent_runner(self, messages: list[dict[str, str]], session_id: str) -> Any:
        """运行器分发:支持工具循环底座的运行器携带会话执行,其余走单次调用契约。"""

        runner = self.agent_runner
        run_with_session = getattr(runner, "run_with_session", None)
        if callable(run_with_session):
            session, _variants = self.source.get_session(session_id)
            return run_with_session(messages, session=session)
        return runner.run(messages)

    def _segment_manager(self, owner_id: str, mode: str) -> MemorySegmentManager | None:
        """legacy 或未装配仓库时不启用 Segment;配置非法在此明确失败。"""

        if mode == "legacy" or self.segment_repository is None:
            return None
        settings = SegmentSettings.from_env()
        return MemorySegmentManager(
            repository=self.segment_repository,
            owner_id=owner_id,
            settings=settings,
            counter=self._segment_counter or counter_from_env()[0],
            summarizer=self._segment_summarizer,
        )

    @staticmethod
    def _segment_rows(preparation: SegmentPreparation, turned: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """页面展示用的 Segment 明细;只放安全摘要与追溯字段。"""

        turn_by_event = {row["event_id"]: row["turn_id"] for row in turned}
        rows: list[dict[str, Any]] = []
        for segment in preparation.segments:
            rows.append(
                {
                    "segment_id": segment.segment_id,
                    "turn_id": turn_by_event.get(segment.start_event_id, ""),
                    "start_event_id": segment.start_event_id,
                    "end_event_id": segment.end_event_id,
                    "source_event_ids": list(segment.source_event_ids),
                    "event_count": len(segment.source_event_ids),
                    "source_hash_short": segment.source_hash[:19],
                    "status": segment.status,
                    "generation_mode": segment.generation_mode,
                    "source_tokens": segment.source_tokens,
                    "summary_tokens": segment.summary_tokens,
                    "cache_hit": segment.segment_id in preparation.hit_ids,
                    "summary_excerpt": segment.summary_content[:600],
                }
            )
        return rows

    @staticmethod
    def _default_request(events: tuple[SessionEvent, ...]) -> SessionEvent:
        for event in reversed(events):
            if event.type == "user_message":
                return event
        raise CurrentRequestNotFound("session has no user message")

    @staticmethod
    def _current_request(events: tuple[SessionEvent, ...], event_id: str) -> SessionEvent:
        event = next((row for row in events if row.event_id == event_id), None)
        if event is None:
            raise CurrentRequestNotFound(event_id)
        if event.type != "user_message":
            raise CurrentRequestInvalid(event_id)
        return event

    @staticmethod
    def _history_session(
        session: SessionCase,
        events: tuple[SessionEvent, ...],
        current: SessionEvent,
    ) -> SessionCase:
        source_hash = canonical_json_hash(
            {
                "source_session_hash": session.source_hash,
                "current_request_event_id": current.event_id,
                "history_event_ids": [event.event_id for event in events],
            }
        )
        return dataclasses.replace(
            session,
            current_question=current.content,
            events=events,
            source_hash=source_hash,
            source_path=f"{session.source_path}#{current.event_id}",
        )

    @staticmethod
    def _summary_status(compiled: Any, preparation: SegmentPreparation | None = None) -> tuple[str, str]:
        warnings = " ".join(compiled.warnings)
        if preparation is not None:
            warnings = f"{warnings} {' '.join(preparation.warnings)}"
            if preparation.fallbacks > 0:
                return "FALLBACK", "EXTRACTIVE_FALLBACK_USED"
        if compiled.build_model_calls > 0 or (preparation is not None and preparation.model_calls > 0):
            return "SUCCEEDED", "LLM_SUMMARY_CREATED"
        if compiled.build_cache_hits > 0 or (preparation is not None and preparation.cache_hits > 0):
            return "SKIPPED", "SUMMARY_CACHE_HIT"
        if "调用失败" in warnings or "LLM 不可用" in warnings or "fallback" in warnings.lower():
            return "FALLBACK", "EXTRACTIVE_FALLBACK_USED"
        return "SKIPPED", "NO_LLM_SUMMARY_NEEDED"

    @staticmethod
    def _decisions(compiled: Any, classifications: dict[str, str]) -> list[dict[str, Any]]:
        result = compiled.build_result
        if result is None:
            return []
        return [
            {
                "item_id": decision.item_id,
                "classification": classifications.get(decision.item_id, "required"),
                "action": decision.action.value,
                "reason": decision.reason,
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
                "output_content": decision.output_content,
                "source_id": decision.source_id,
                "decision_source": "CODE_RULE",
            }
            for decision in result.report.decisions
        ]

    @staticmethod
    def _item_counts(classifications: dict[str, str], decisions: list[dict[str, Any]]) -> dict[str, int]:
        counts = {name: 0 for name in ("required", "compressible", "reference_only", "distractor")}
        for classification in classifications.values():
            counts[classification] = counts.get(classification, 0) + 1
        action_names = {"kept": "retained", "compressed": "compressed", "referenced": "referenced"}
        counts.update({"retained": 0, "compressed": 0, "referenced": 0, "omitted": 0})
        for decision in decisions:
            target = action_names.get(str(decision["action"]), "omitted")
            counts[target] += 1
        return counts
