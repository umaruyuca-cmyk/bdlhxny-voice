"""Run State 读取契约（重构方案 D1/P2a）。

运行状态投影（final_response / events / interrupts 等）的读取端口。
P2a 只做端口抽象与 InMemory 实现迁出 ``api/routes.py``，**不切换**读取
来源：cognitive 路径继续由内存快照 + RunRegistry 共同服务，行为与迁移前
一致。

后续切换（P2b，前置依赖 P6a 的 Java Run Projection/Event 真源就绪）：

- legacy 路径读 LangGraph Checkpointer（真源在 checkpoint schema）；
- cognitive 路径读 Java Data Plane 的 Run Projection/Event API；
- ``InMemoryRunStateReader`` 仅保留测试与显式开发降级用途。

禁止事项（审计 H1）：不得为运行快照新建第三套 Python PostgreSQL 表。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# 运行状态投影：api.projections.public_state 所消费的 state dict 结构
RunState = dict[str, Any]


@runtime_checkable
class RunStateReader(Protocol):
    """按 run_id 读取运行状态投影；用户鉴权由 API 层 authorize_run 完成。"""

    def load(self, run_id: str, user_id: str | None) -> RunState | None: ...


class RunStateWriter(Protocol):
    """保存运行状态投影；写入方必须同时提供归属用户。"""

    def save(self, run_id: str, user_id: str | None, state: RunState) -> None: ...


class RunStateStore(RunStateReader, RunStateWriter, Protocol):
    """当前 API 所需的读写端口。

    P6a 后 Java 实现是该端口的唯一生产实现；不要通过 ``Any`` 或未声明的
    ``put`` 方法绕过用户范围与写入契约。
    """


class InMemoryRunStateReader:
    """本地开发/测试的进程内快照（自 api/routes.py 的 InMemoryRunStore 行为等价迁出）。

    仅测试与显式开发降级可用；进程重启即丢、多实例不一致，
    不得作为生产读取源（审查 SW-R-001）。
    """

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def save(self, run_id: str, user_id: str | None, state: RunState) -> None:
        state_owner = state.get("user_id")
        if state_owner is not None and user_id is not None and str(state_owner) != str(user_id):
            raise ValueError("run state user_id does not match writer scope")
        state["user_id"] = user_id
        self._runs[run_id] = state

    def load(self, run_id: str, user_id: str | None) -> RunState | None:
        state = self._runs.get(run_id)
        if state is None:
            return None
        owner = state.get("user_id")
        if user_id is not None and (owner is None or str(owner) != str(user_id)):
            return None
        return state
