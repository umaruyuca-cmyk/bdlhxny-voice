from langgraph.types import Command

from stockwise_analysis.runtimes.langgraph.graphs.root_graph import build_root_graph, initial_state


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


def test_missing_context_interrupts_and_resume_continues_same_thread():
    graph = build_root_graph()
    run_id = "test-resume"
    config = {"configurable": {"thread_id": run_id}}
    interrupted = graph.invoke(initial_state(run_id, {"message": "请做综合分析"}), config=config)

    assert interrupted["__interrupt__"]
    resumed = graph.invoke(Command(resume={"symbol": "600000"}), config=config)

    assert resumed["final_response"] is not None
    assert resumed["status"] in {"SUCCESS", "PARTIAL"}


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
