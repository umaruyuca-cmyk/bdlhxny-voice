"""生产用例仓库映射测试:data 服务 /camelCase 视图 → ComparisonCase。

此前单测用内存仓库,没护住视图键名映射(expectedChecks/allowedTools);
本测试按 data 服务真实返回形状构造视图,防止再次漂移。
不访问真实服务。
"""

from __future__ import annotations

from bdlh_runtime.experiments.public_case_repository import _case_from_view


def _view(**overrides) -> dict:
    view = {
        "id": "cmp-x-01",
        "title": "示例用例",
        "version": 2,
        "message": "固定问题",
        "scene": "general",
        "allowedTools": ["a.tool", "b.tool"],
        "expectedChecks": {
            "test_type": "COMPARISON_CASE",
            "category": "multi",
            "category_label": "多工具",
            "fixture_set_id": "cmp-fixtures-v1",
            "call_relation": {
                "required_calls": [{"tool": "a.tool", "arguments": {"q": "x"}}],
                "required_dependencies": [{"from": "a.tool.id", "to": "b.tool.id"}],
                "forbidden_calls": ["c.write"],
                "stop_when_facts_available": ["ORD-1"],
            },
            "mock_fixtures": [{"tool": "a.tool", "match_arguments": {"q": "x"}, "result": {"id": "ORD-1"}}],
        },
    }
    view.update(overrides)
    return view


def test_view_camel_case_keys_mapped():
    case = _case_from_view(_view())
    assert case is not None
    assert case.case_id == "cmp-x-01"
    assert case.case_version == 2
    assert case.allowed_tools == ("a.tool", "b.tool")
    assert case.default_visible_tools == ("a.tool", "b.tool")
    assert case.call_relation.required_calls[0].tool == "a.tool"
    assert case.call_relation.required_dependencies[0].to_tool == "b.tool"
    assert case.conditions["mock_fixtures"][0]["tool"] == "a.tool"


def test_old_case_without_explicit_test_type_filtered():
    """因历史运行外键保留的旧用例(expected_checks 无 test_type)不进入对比用例仓库。"""
    legacy = _view(
        id="miss-01",
        expectedChecks={"category": "拦截", "fastpath": "forbidden", "forbidden_actions": ["place_order"]},
    )
    assert _case_from_view(legacy) is None


def test_case_without_allowed_tools_skipped():
    assert _case_from_view(_view(allowedTools=[])) is None
