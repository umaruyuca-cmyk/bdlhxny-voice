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
    publisher = RunEventPublisher("run-1", flush=lambda events: flushed.append(list(events)), flush_batch=3)
    publisher.attach(recorder)  # 1 条(run.started 补投)
    for index in range(4):
        recorder.emit("context.completed", {"index": index})  # 累计 5 条
    # 达到 3 条阈值即增量落库,剩余 2 条留在缓冲
    assert [len(batch) for batch in flushed] == [3]
    publisher.complete()  # 终态:剩余事件全部落库 + done 置位
    assert [len(batch) for batch in flushed] == [3, 2]
    assert publisher.done
    assert publisher.backlog_after(0) and publisher.last_sequence == 5


def test_flush_failure_keeps_pending_and_retries_next_flush():
    """首次保存失败、第二次成功(修复方案 P1-5):失败批次保留在 pending,
    下一批 flush 时重试;重复投递由数据服务 (run_id, sequence) 幂等去重。"""
    calls: list[list[str]] = []

    def flaky_flush(events):
        calls.append([event["eventType"] for event in events])
        if len(calls) == 1:
            raise RuntimeError("data 服务暂时不可达")

    recorder = _recorder()
    publisher = RunEventPublisher("run-1", flush=flaky_flush, flush_batch=2)
    publisher.attach(recorder)  # 1 条(run.started 补投):不足一批,不触发 flush
    recorder.emit("context.completed", {})  # 累计 2 条 → 首次 flush 失败
    assert calls == [["run.started", "context.completed"]]
    recorder.emit("context.completed", {"index": 1})  # 累计 3 条 → 再次 flush:重试成功
    # 重试批次包含首次失败的全部事件,不是只投递新事件
    assert calls[1] == ["run.started", "context.completed", "context.completed"]
    publisher.complete()  # 游标已推进到全部事件:终态 flush 无新增批次
    assert publisher.done
    assert len(calls) == 2


def test_flush_failure_at_completion_retries_on_final_flush():
    """complete() 前失败:终态 flush 重试全部未落库事件(至少一次投递)。"""
    calls: list[list[str]] = []

    def fail_then_succeed(events):
        calls.append([event["eventType"] for event in events])
        if len(calls) == 1:
            raise RuntimeError("data 服务暂时不可达")

    recorder = _recorder()
    publisher = RunEventPublisher("run-1", flush=fail_then_succeed, flush_batch=1)
    publisher.attach(recorder)  # 1 条 → 首次 flush 失败,游标不推进
    assert len(calls) == 1
    publisher.complete()  # 终态 flush 重试同一批事件(接收方按 sequence 幂等)
    assert calls[1] == calls[0]
    assert publisher.done
    assert len(calls) == 2


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
