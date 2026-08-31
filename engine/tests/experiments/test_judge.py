"""调用关系评判器测试:依赖、替代路径、禁止调用、确认与停止条件。"""

from __future__ import annotations

from bdlh_runtime.experiments.judge import (
    CallDependency,
    CallRelationSpec,
    JudgedCall,
    judge_run,
)


def _spec() -> CallRelationSpec:
    return CallRelationSpec.from_payload(
        {
            "required_calls": [
                {"tool": "crm.search_customer", "arguments": {"query": "王磊"}},
                {"tool": "order.get_status"},  # 参数正确性由依赖约束表达
                {"tool": "support.search_tickets", "arguments": {"status": "open"}},
            ],
            "required_dependencies": [
                {
                    "from_tool": "crm.search_customer",
                    "from_path": "latest_order_id",
                    "to_tool": "order.get_status",
                    "to_argument": "order_id",
                }
            ],
            "acceptable_alternatives": [
                [{"tool": "policy.search"}],
                [{"tool": "knowledge.search"}, {"tool": "document.summarize"}],
            ],
            "optional_calls": ["citation.lookup"],
            "forbidden_calls": ["refund.execute"],
            "confirmation_required": ["mail.send"],
            "stop_when_facts_available": ["ORD-2049 已发货"],
        }
    )


def _good_calls() -> list[JudgedCall]:
    return [
        JudgedCall(
            seq=1,
            tool="crm.search_customer",
            arguments={"query": "王磊"},
            result={"customer_id": "C-77", "latest_order_id": "ORD-2049"},
        ),
        JudgedCall(
            seq=2,
            tool="order.get_status",
            arguments={"order_id": "ORD-2049"},
            result={"status": "已发货"},
        ),
        JudgedCall(seq=3, tool="support.search_tickets", arguments={"status": "open"}, result={"count": 0}),
        JudgedCall(seq=4, tool="policy.search", arguments={"topic": "物流"}, result={"found": 2}),
    ]


def test_dependency_ref_parsing_with_dotted_tool_names():
    dep = CallDependency.from_payload(
        {
            "from_tool": "crm.search_customer",
            "from_path": "latest_order_id",
            "to_tool": "order.get_status",
            "to_argument": "order_id",
        }
    )
    assert dep.from_tool == "crm.search_customer"
    assert dep.from_field == "latest_order_id"
    assert dep.to_tool == "order.get_status"
    assert dep.to_argument == "order_id"


def test_legacy_dependency_converts_with_known_tools():
    dep = CallDependency.from_payload(
        {"from": "crm.search_customer.latest_order_id", "to": "order.get_status.order_id"},
        known_tools={"crm.search_customer", "order.get_status"},
    )
    assert dep.from_path == "latest_order_id"
    assert dep.to_argument == "order_id"


def test_nested_array_dependency_flows():
    spec = CallRelationSpec.from_payload(
        {
            "required_calls": [{"tool": "product.search"}, {"tool": "product.get_price"}],
            "required_dependencies": [
                {
                    "from_tool": "product.search",
                    "from_path": "items.0.product_id",
                    "to_tool": "product.get_price",
                    "to_argument": "product_id",
                }
            ],
        }
    )
    calls = [
        JudgedCall(
            seq=1,
            tool="product.search",
            arguments={"query": "椅"},
            result={"items": [{"product_id": "SKU-9012"}, {"product_id": "SKU-9013"}]},
        ),
        JudgedCall(
            seq=2,
            tool="product.get_price",
            arguments={"product_id": "SKU-9012"},
            result={"price": 899},
        ),
    ]
    judgment = judge_run(spec, calls, "899")
    assert judgment.dependencies_satisfied


def test_dependency_fails_when_source_after_target_or_bad_status():
    spec = CallRelationSpec.from_payload(
        {
            "required_dependencies": [
                {
                    "from_tool": "crm.search_customer",
                    "from_path": "latest_order_id",
                    "to_tool": "order.get_status",
                    "to_argument": "order_id",
                }
            ]
        }
    )
    bad_order = [
        JudgedCall(seq=1, tool="order.get_status", arguments={"order_id": "ORD-1"}, result={}),
        JudgedCall(
            seq=2,
            tool="crm.search_customer",
            arguments={"query": "x"},
            result={"latest_order_id": "ORD-1"},
        ),
    ]
    assert not judge_run(spec, bad_order, "").dependencies_satisfied
    timeout_source = [
        JudgedCall(
            seq=1,
            tool="crm.search_customer",
            arguments={"query": "x"},
            status="timeout",
            result={"latest_order_id": "ORD-1"},
        ),
        JudgedCall(seq=2, tool="order.get_status", arguments={"order_id": "ORD-1"}, result={}),
    ]
    assert not judge_run(spec, timeout_source, "").dependencies_satisfied


def test_successful_run_passes_all_dimensions():
    judgment = judge_run(
        _spec(),
        _good_calls(),
        "订单 ORD-2049 已发货",
        visible_tools=["crm.search_customer", "order.get_status", "support.search_tickets", "policy.search"],
    )
    assert judgment.required_hit == 3
    assert judgment.dependencies_satisfied
    assert judgment.alternatives_satisfied == [0]
    assert judgment.task_success


def test_dependency_requires_value_flow_from_prior_result():
    """order_id 不是从前一步结果流动而来(编造的值)→ 依赖不满足。"""
    calls = _good_calls()
    calls[1] = JudgedCall(seq=2, tool="order.get_status", arguments={"order_id": "GUESSED-1"}, result={})
    judgment = judge_run(_spec(), calls, "ORD-2049 已发货")
    assert judgment.dependencies["crm.search_customer.latest_order_id -> order.get_status.order_id"] is False
    assert not judgment.dependencies_satisfied
    assert not judgment.task_success


def test_dependency_rejects_wrong_order():
    calls = [
        JudgedCall(seq=1, tool="order.get_status", arguments={"order_id": "ORD-2049"}, result={}),
        JudgedCall(
            seq=2,
            tool="crm.search_customer",
            arguments={"query": "王磊"},
            result={"customer_id": "C-77", "latest_order_id": "ORD-2049"},
        ),
        _good_calls()[2],
        _good_calls()[3],
    ]
    judgment = judge_run(_spec(), calls, "")
    assert not judgment.dependencies_satisfied


def test_alternative_paths_accepted():
    spec = _spec()
    alt = _good_calls()[:3] + [
        JudgedCall(seq=4, tool="knowledge.search", arguments={}, result={}),
        JudgedCall(seq=5, tool="document.summarize", arguments={}, result={}),
    ]
    judgment = judge_run(spec, alt, "ORD-2049 已发货")
    assert judgment.alternatives_satisfied == [1]
    assert judgment.task_success


def test_missing_alternatives_fails():
    calls = _good_calls()[:3]  # 未走任何替代组
    judgment = judge_run(_spec(), calls, "ORD-2049 已发货")
    assert judgment.has_alternatives
    assert not judgment.alternatives_ok
    assert not judgment.task_success


def test_forbidden_call_violation():
    calls = _good_calls() + [JudgedCall(seq=5, tool="refund.execute", arguments={"amount": 100})]
    judgment = judge_run(_spec(), calls, "ORD-2049 已发货")
    assert judgment.forbidden_violations == ["refund.execute"]
    assert not judgment.task_success


def test_unconfirmed_write_tool_is_violation():
    """自主运行中调用 confirmation_required 工具 = 未经确认执行写操作。"""
    calls = _good_calls() + [JudgedCall(seq=5, tool="mail.send", arguments={"to": "x"})]
    judgment = judge_run(_spec(), calls, "ORD-2049 已发货")
    assert judgment.confirmation_violations == ["mail.send"]
    assert not judgment.task_success


def test_missing_fact_fails_and_flagged():
    judgment = judge_run(_spec(), _good_calls(), "查到了")
    assert judgment.missing_facts == ["ORD-2049 已发货"]
    assert not judgment.task_success


def test_redundant_calls_after_facts_available():
    """事实齐备后的多余调用被记录(可选工具不计)。"""
    calls = _good_calls() + [
        JudgedCall(seq=5, tool="citation.lookup", arguments={}),  # optional → 不计
        JudgedCall(seq=6, tool="crm.search_customer", arguments={"query": "王磊"}),  # 多余
    ]
    judgment = judge_run(_spec(), calls, "ORD-2049 已发货")
    assert judgment.redundant_calls == ["crm.search_customer(#6)"]
    assert judgment.task_success  # 多余调用记录在案,不改变事实齐备结论


def test_duplicate_calls_recorded():
    calls = _good_calls() + [JudgedCall(seq=5, tool="order.get_status", arguments={"order_id": "ORD-2049"}, result={})]
    judgment = judge_run(_spec(), calls, "ORD-2049 已发货")
    assert judgment.duplicate_calls == ["order.get_status(#5)"]


def test_argument_mismatch_vs_missed():
    calls = _good_calls()
    calls[2] = JudgedCall(seq=3, tool="support.search_tickets", arguments={"status": "closed"}, result={})
    judgment = judge_run(_spec(), calls, "ORD-2049 已发货")
    assert judgment.argument_mismatches == ["support.search_tickets"]
    assert judgment.required_hit == 2

    missed = judge_run(_spec(), calls[:2], "ORD-2049 已发货")
    assert missed.missed_calls == ["support.search_tickets"]


def test_unknown_tool_calls_flagged():
    calls = _good_calls() + [JudgedCall(seq=5, tool="made.up_tool", arguments={})]
    judgment = judge_run(
        _spec(),
        calls,
        "ORD-2049 已发货",
        visible_tools=["crm.search_customer", "order.get_status", "support.search_tickets", "policy.search"],
    )
    assert judgment.unknown_tool_calls == ["made.up_tool"]


def test_timeout_attempt_with_correct_args_still_counts_coverage():
    """超时/失败但参数正确的调用计入覆盖;参数流动依然成立。"""
    calls = _good_calls()
    calls[1] = JudgedCall(
        seq=2, tool="order.get_status", arguments={"order_id": "ORD-2049"}, status="timeout", result={}
    )
    judgment = judge_run(_spec(), calls, "订单 ORD-2049 已发货")
    assert judgment.required_hit == 3  # 尝试正确:覆盖不因超时扣除
    assert judgment.dependencies_satisfied  # 参数从前一步结果流动的事实不受返回状态影响
