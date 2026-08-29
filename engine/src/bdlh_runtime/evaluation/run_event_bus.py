"""运行事件实时发布器(阶段二:运行中实时可见,设计 §7.2/§10)。

职责:
- 订阅 RunRecorder 事件流(per-run 事件发布器);
- 面向 SSE 订阅者提供积压补发(``backlog_after``)与实时等待(Condition);
- 执行中增量持久化关键事件:积满 ``flush_batch`` 条或遇 run.completed 即
  通过注入的 flush 回调落库(data 服务 ON CONFLICT 幂等,至少一次投递);
- ``complete()`` 终态化:最终 flush + 唤醒所有订阅者(SSE 由此关流)。

发布器只依赖注入的 flush 回调,不直接持有 DataClient(可测试);
执行线程与 SSE 线程通过 Condition 交互,无需跨事件循环桥接。
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from bdlh_runtime.evaluation.run_telemetry import EVENT_RUN_COMPLETED

#: 注册表上限:超出时驱逐已完成发布器(单实例部署;防长进程内存增长)
_MAX_PUBLISHERS = 50


class RunEventPublisher:
    """per-run 事件发布器:执行线程生产,SSE 订阅者与增量落库消费。"""

    def __init__(
        self,
        run_id: str,
        *,
        flush: Callable[[list[dict[str, Any]]], None] | None = None,
        flush_batch: int = 10,
    ) -> None:
        self.run_id = run_id
        self._flush = flush
        self._flush_batch = max(1, int(flush_batch))
        self._cond = threading.Condition()
        self._events: list[dict[str, Any]] = []
        self._flushed_count = 0
        self._done = False

    # -- 生产端(执行线程) ---------------------------------------------------

    def attach(self, recorder: Any) -> None:
        """订阅 RunRecorder 事件流;先补投已产生的事件(如构造期 run.started)。"""
        for event in list(recorder.record.events):
            self._on_event(event)
        recorder.add_event_listener(self._on_event)

    def _on_event(self, event: dict[str, Any]) -> None:
        with self._cond:
            self._events.append(dict(event))
            should_flush = (
                len(self._events) - self._flushed_count >= self._flush_batch
                or event.get("eventType") == EVENT_RUN_COMPLETED
            )
            self._cond.notify_all()
        if should_flush:
            self.flush()

    def complete(self) -> None:
        """运行终态:最终落库 + 唤醒订阅者(SSE 见 run.completed 后关流)。"""
        with self._cond:
            self._done = True
            self._cond.notify_all()
        self.flush()

    # -- 消费端(SSE 线程) ---------------------------------------------------

    def backlog_after(self, last_sequence: int) -> list[dict[str, Any]]:
        """返回 sequence 大于 last_sequence 的已缓冲事件(断线补发)。"""
        with self._cond:
            return [dict(event) for event in self._events if int(event.get("sequence") or 0) > last_sequence]

    @property
    def done(self) -> bool:
        with self._cond:
            return self._done

    @property
    def last_sequence(self) -> int:
        with self._cond:
            return int(self._events[-1]["sequence"]) if self._events else 0

    def wait(self, timeout: float) -> bool:
        """等待新事件或终态;返回 True 表示状态有变化(否则为超时,可发心跳)。"""
        with self._cond:
            return self._cond.wait(timeout)

    # -- 增量持久化 -----------------------------------------------------------

    def flush(self) -> None:
        """把未落库事件交给注入回调(失败只打日志;完成后的全量落库会重写)。"""
        if self._flush is None:
            return
        with self._cond:
            pending = [dict(event) for event in self._events[self._flushed_count :]]
            self._flushed_count = len(self._events)
        if not pending:
            return
        try:
            self._flush(pending)
        except Exception as exc:  # noqa: BLE001 —— 增量落库失败不阻断执行
            print(f"[run_event_bus] 事件增量落库失败(run={self.run_id}):{type(exc).__name__}: {exc}")


class RunEventPublisherRegistry:
    """进程内发布器注册表(SSE 按 run_id 查找;单实例部署前提)。"""

    def __init__(self, *, capacity: int = _MAX_PUBLISHERS) -> None:
        self._lock = threading.Lock()
        self._publishers: dict[str, RunEventPublisher] = {}
        self._capacity = capacity

    def register(self, publisher: RunEventPublisher) -> RunEventPublisher:
        with self._lock:
            if len(self._publishers) >= self._capacity:
                for key, candidate in list(self._publishers.items()):
                    if candidate.done and key != publisher.run_id:
                        del self._publishers[key]
            self._publishers[publisher.run_id] = publisher
            return publisher

    def get(self, run_id: str) -> RunEventPublisher | None:
        with self._lock:
            return self._publishers.get(run_id)


_REGISTRY = RunEventPublisherRegistry()


def register_publisher(publisher: RunEventPublisher) -> RunEventPublisher:
    return _REGISTRY.register(publisher)


def get_publisher(run_id: str) -> RunEventPublisher | None:
    return _REGISTRY.get(run_id)


__all__ = ["RunEventPublisher", "RunEventPublisherRegistry", "get_publisher", "register_publisher"]
