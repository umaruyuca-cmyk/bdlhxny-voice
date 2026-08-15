from langgraph.types import Command

from bdlh_runtime.runtimes.langgraph.graphs.root_graph import build_root_graph, initial_state
from bdlh_runtime.runtimes.langgraph.graphs.state import merge_state_items


def test_dynamic_snapshot_workflow_completes_with_mock_data():
    graph = build_root_graph()
    run_id = "test-snapshot"
    result = graph.invoke(
        initial_state(run_id, {"message": "请分析 600000 的技术趋势"}),
        config={"configurable": {"thread_id": run_id}},
    )

    assert result["status"] in {"SUCCESS", "PARTIAL"}
    assert result["final_response"]["analysis_id"] == run_id
    assert any(item["event_type"] == "run.finished" for item in result["events"])
    assert result["workflow_plan"]["revision"] > 0


def test_nested_graph_outputs_do_not_duplicate_append_only_state():
    """子图返回入口快照时，事件、Observation、实体和对话不得重复追加。"""
    graph = build_root_graph()
    run_id = "test-no-duplicate-state"
    result = graph.invoke(
        initial_state(run_id, {"message": "分析 600000"}),
        config={"configurable": {"thread_id": run_id}},
    )

    for field, id_field in (
        ("events", "event_id"),
        ("observations", "observation_id"),
        ("entities", "entity_id"),
    ):
        values = result.get(field, [])
        ids = [item[id_field] for item in values if item.get(id_field)]
        assert len(ids) == len(set(ids)), f"{field} contains duplicate ids"

    conversation = result.get("conversation", [])
    assert len(conversation) == len({repr(item) for item in conversation})


def test_state_reducer_preserves_a_genuinely_repeated_new_message():
    """相同内容作为新增量再次出现时应保留，不能按内容全局去重。"""
    first = {"role": "user", "content": "继续分析", "run_id": "run-1"}
    repeated = {"role": "user", "content": "继续分析", "run_id": "run-2"}

    assert merge_state_items([first], [repeated]) == [first, repeated]


def test_state_reducer_collapses_a_child_graph_full_snapshot():
    """子图返回包含入口状态的完整列表时只合并新增尾部。"""
    first = {"event_id": "event-1"}
    second = {"event_id": "event-2"}

    assert merge_state_items([first], [first, second]) == [first, second]


def test_missing_context_interrupts_and_resume_continues_same_thread():
    """technical 分析缺 symbol 时 interrupt；resume 后继续（v2.1：仅需标的的类型才补问）。"""
    graph = build_root_graph()
    run_id = "test-resume"
    config = {"configurable": {"thread_id": run_id}}
    interrupted = graph.invoke(initial_state(run_id, {"message": "请做技术分析"}), config=config)

    assert interrupted["__interrupt__"]
    resumed = graph.invoke(Command(resume={"symbol": "600000"}), config=config)

    assert resumed["final_response"] is not None
    assert resumed["status"] in {"SUCCESS", "PARTIAL"}


def test_direct_response_knowledge_question_no_tool():
    """v2.1 §3：知识问答走 direct_response，不调工具、不要求股票代码。"""
    graph = build_root_graph()
    run_id = "test-knowledge"
    result = graph.invoke(
        initial_state(run_id, {"message": "什么是市盈率？"}),
        config={"configurable": {"thread_id": run_id}},
    )

    assert result["status"] == "SUCCESS"
    assert result["intent_route"]["mode"] == "direct_response"
    assert result["final_response"] is not None
    assert result["final_response"]["mode"] == "direct_response"
    # 不应产生 observations（没调工具）
    assert result.get("observations", []) == []


def test_comprehensive_no_symbol_not_interrupted():
    """v2.1 §8：综合分析无 symbol 不 interrupt（可以是市场综合分析）。"""
    graph = build_root_graph()
    run_id = "test-comprehensive-no-symbol"
    result = graph.invoke(
        initial_state(run_id, {"message": "请做综合分析"}),
        config={"configurable": {"thread_id": run_id}},
    )

    # 不应 interrupt，应完成
    assert "__interrupt__" not in result
    assert result["status"] in {"SUCCESS", "PARTIAL", "LIMITED"}
    assert result["final_response"] is not None


def test_cross_turn_symbol_inheritance():
    """v2.1 §7.3：同 thread 第二轮缺 symbol 时继承前文标的。

    场景：第一轮"分析 600519 技术趋势"（有 symbol），第二轮"请做基本面分析"
    （无 symbol）→ 应继承 600519，不 interrupt。
    """
    graph = build_root_graph()
    thread_id = "test-cross-turn"
    config = {"configurable": {"thread_id": thread_id}}
    # 第一轮：有 symbol 的技术分析
    graph.invoke(
        initial_state("run-1", {"message": "分析 600519 的技术趋势"}, thread_id=thread_id),
        config=config,
    )
    # 第二轮：基本面分析，无 symbol → 继承 600519
    result2 = graph.invoke(
        initial_state("run-2", {"message": "请做基本面分析"}, thread_id=thread_id),
        config=config,
    )
    # 应继承前文标的，不 interrupt
    assert "__interrupt__" not in result2
    assert result2["intent"]["symbol"] == "600519"


def test_optional_confirmation_interrupts_after_response_and_resumes():
    graph = build_root_graph()
    run_id = "test-confirmation"
    config = {"configurable": {"thread_id": run_id}}
    interrupted = graph.invoke(
        initial_state(run_id, {"message": "分析 600000", "require_confirmation": True}),
        config=config,
    )

    assert interrupted["__interrupt__"]
    assert interrupted["final_response"] is not None
    resumed = graph.invoke(Command(resume={"confirmed": True}), config=config)

    assert resumed["confirmation"] == {"confirmed": True}
    assert resumed["status"] in {"SUCCESS", "PARTIAL"}
