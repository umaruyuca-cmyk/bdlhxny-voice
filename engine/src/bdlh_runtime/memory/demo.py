"""系统演示管线:启动后自动以真实 LLM 执行 构建 → Agent 运行,产出公开展示数据。

设计(用户目标:无登录、全模块真实数据自动上屏):
- 以系统演示账号(``DEMO_OWNER``)在文件 Store 下执行,与真实用户数据
  (所有者隔离)互不干扰;展示走公开只读端点,无需登录;
- 管线与登录工作台完全同构:Segment 分段(incremental 语义,真实 LLM 摘要,
  失败回退抽取式)+ LLM 辅助分类 + 预算选择 + 冻结工件 + Agent 工具循环运行;
- 成本守卫:幂等键含会话来源哈希与算法版本——同会话同配置只执行一次,
  重启/重复调用直接复用既有构建与运行终态,不产生新调用;
- 未配置 ``LLM_API_KEY`` 时整个管线跳过并如实返回 skipped(页面展示
  诚实的空态,不伪造数据)。
"""

from __future__ import annotations

import os
from typing import Any

from .segments import InMemoryMemorySegmentRepository
from .service import ContextWorkbenchService
from .sources import FrozenSessionSource
from .store import ContextBuildStore

DEMO_OWNER = "system-demo"

#: 共享的进程级 Segment 仓库:演示构建间命中来源哈希直接复用(真实复用演示)
_demo_segment_repo: InMemoryMemorySegmentRepository | None = None


def _segment_repository() -> InMemoryMemorySegmentRepository:
    global _demo_segment_repo
    if _demo_segment_repo is None:
        _demo_segment_repo = InMemoryMemorySegmentRepository()
    return _demo_segment_repo


def demo_service(store: ContextBuildStore | None = None) -> ContextWorkbenchService:
    """演示管线的服务实例:冻结来源 + 内存 Segment 仓库 + 真实 LLM 装配。"""

    return ContextWorkbenchService(
        store or ContextBuildStore(os.environ.get("ARTIFACTS_DIR") or "var/artifacts"),
        source=FrozenSessionSource(),
        # incremental 语义:Segment 摘要走 LLMSummarizer(有 key 真调,无 key
        # 内部回退抽取式);分类器由 from_env(llm_summary=True) 装配
        segment_repository=_segment_repository(),
    )


def run_demo_pipeline(
    *,
    artifacts_dir: str,
    session_ids: list[str] | None = None,
    store: ContextBuildStore | None = None,
) -> list[dict[str, Any]]:
    """执行一轮演示管线;返回逐会话结果(供启动日志与测试断言)。

    全程无人工操作:幂等键守卫下,首次真实执行,其后复用终态。
    """

    if not (os.environ.get("LLM_API_KEY") or "").strip():
        return [
            {"session_id": session_id, "skipped": "LLM_UNAVAILABLE", "status": "SKIPPED"}
            for session_id in (session_ids or [])
        ]

    # 必须复用调用方(公开端点)的同一 Store 实例:文件 Store 在初始化时
    # 一次性加载内存,跨实例不共享写入
    service = demo_service(store or ContextBuildStore(artifacts_dir))
    if session_ids is None:
        session_ids = [str(row["session_id"]) for row in service.sessions()]

    results: list[dict[str, Any]] = []
    for session_id in session_ids:
        result: dict[str, Any] = {"session_id": session_id}
        try:
            overview = service.overview(session_id)
            idem_base = f"demo-{session_id}-{str(overview['source_hash'])[:24]}-v2"
            build, replay = service.create_build(
                owner_id=DEMO_OWNER,
                session_id=session_id,
                current_request_event_id=str(overview["default_current_request_event_id"]),
                algorithm="budgeted-hybrid-v1",
                # 幂等守卫:来源哈希或算法变化才产生新构建(新 LLM 调用)
                idempotency_key=idem_base,
            )
            build_id = str(build["build_id"])
            result["build_id"] = build_id
            result["build_replay"] = replay
            if replay and str(build.get("status")) == "FAILED":
                # 上次执行中断/失败(如进程重启被标记):换新幂等键重试一次
                from datetime import UTC, datetime

                suffix = datetime.now(UTC).strftime("%H%M%S")
                build, replay = service.create_build(
                    owner_id=DEMO_OWNER,
                    session_id=session_id,
                    current_request_event_id=str(overview["default_current_request_event_id"]),
                    algorithm="budgeted-hybrid-v1",
                    idempotency_key=f"{idem_base}-r{suffix}",
                )
                build_id = str(build["build_id"])
                result["build_id"] = build_id
                result["build_replay"] = replay
            if not replay:
                # 真实 LLM:分类辅助 1 次 + 摘要 ≤2 次 + Segment 分段摘要
                service.execute_build(build_id, DEMO_OWNER, mode="incremental")

            row = service.store.get(build_id, DEMO_OWNER)
            result["build_status"] = str(row.get("status"))
            if row.get("status") == "COMPLETED" and row.get("artifact_id"):
                # Agent 工具循环运行(真实 LLM);终态复用不重跑
                _snapshot, started = service.start_agent_run(build_id, DEMO_OWNER)
                if started:
                    service.execute_agent_run(build_id, DEMO_OWNER)
                run_row = service.store.get(build_id, DEMO_OWNER)
                agent = run_row.get("agent_run") or {}
                result["agent_status"] = agent.get("status")
                result["agent_replay"] = not started
            else:
                result["agent_status"] = "SKIPPED_BUILD_NOT_COMPLETED"
        except Exception as exc:  # noqa: BLE001 —— 单会话失败不阻塞其余演示
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results
