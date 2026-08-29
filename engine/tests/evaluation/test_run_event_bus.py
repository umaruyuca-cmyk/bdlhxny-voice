"""运行事件实时发布器契约(阶段二:运行中实时可见,设计 §7.2/§10)。

覆盖:既有事件补投、断线积压补发、按批/终态增量 flush、flush 失败抑制、
注册表容量驱逐。全部为内存对象,不触网络。
"""

from __future__ import annotations

from bdlh_runtime.evaluation.run_event_bus import (
    RunEventPublisher,
    RunEventPublisherRegistry,
    get_publisher,
    register_publisher,
)
from bdlh_runtime.evaluation.run_telemetry import RunRecorder


def _recorder() -> RunRecorder:
    return RunRecorder(
        run_key="research-01:native-tool-calling:0",
        case_id="research-01",
        case_version=1,
        variant_id="default",
        snapshot_id="research-01:fixture-v1",
        snapshot_hash="sha256:snap",
        agent_mode="native-tool-calling",
        context_strategy="fixed-case-input",
        model="glm-4.7-flash",
        repeat_index=0,
        message="宁德时代现在什么价",
        category="金融研究",
    )


def test_publisher_replays_existing_events_then_subscribes():
    recorder = _recorder()
    publisher = RunEventPublisher("run-1")
    publisher.attach(recorder)  # run.started 在构造期已发出:attach 必须补投
    recorder.emit("context.completed", {"strategy": "full"})
    assert [event["eventType"] for event in publisher.backlog_after(0)] == [
        "run.started",
        "context.completed",
    ]
    # 断线续传:backlog_after(1) 只补 sequence>1 的部分
    assert [event["sequence"] for event in publisher.backlog_after(1)] == [2]


def test_publisher_flushes_in_batches_and_on_completion():
    flushed: list[list[dict]] = []
    recorder = _recorder()
    publisher = RunEventPublisher(
        "run-1", flush=lambda events: flushed.append(list(events)), flush_batch=3
    )
    publisher.attach(recorder)  # 1 条(run.started 补投)
    for index in range(4):
        recorder.emit("context.completed", {"index": index})  # 累计 5 条
    # 达到 3 条阈值即增量落库,剩余 2 条留在缓冲
    assert [len(batch) for batch in flushed] == [3]
    publisher.complete()  # 终态:剩余事件全部落库 + done 置位
    assert [len(batch) for batch in flushed] == [3, 2]
    assert publisher.done
    assert publisher.backlog_after(0) and publisher.last_sequence == 5


def test_flush_failure_is_suppressed_and_events_retained():
    attempts: list[int] = []

    def bad_flush(events):
        attempts.append(len(events))
        raise RuntimeError("data 服务不可达")

    recorder = _recorder()
    publisher = RunEventPublisher("run-1", flush=bad_flush, flush_batch=1)
    publisher.attach(recorder)
    recorder.emit("context.completed", {})  # 每条事件(含补投)都达到阈值 → 异常被抑制,不影响执行
    assert attempts == [1, 1]  # run.started(补投) + context.completed 各触发一次失败 flush
    assert publisher.backlog_after(0)  # 事件仍在缓冲,后续可重试
    publisher.complete()  # 已全部 flush 过 → 无新增回调;done 置位
    assert publisher.done and attempts == [1, 1]


def test_registry_evicts_done_publishers_when_full():
    registry = RunEventPublisherRegistry(capacity=2)
    first = RunEventPublisher("a")
    second = RunEventPublisher("b")
    third = RunEventPublisher("c")
    registry.register(first)
    registry.register(second)
    first.complete()  # a 终态 → 可被驱逐
    registry.register(third)
    assert registry.get("a") is None
    assert registry.get("b") is not None
    assert registry.get("c") is not None


def test_module_level_registry_roundtrip():
    publisher = register_publisher(RunEventPublisher("run-registry-test"))
    assert get_publisher("run-registry-test") is publisher
