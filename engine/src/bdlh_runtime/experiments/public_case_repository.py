"""公开对比用例仓库:engine 侧的用例读取适配层。

生产实现经 data 服务读取用例库版本(PostgreSQL 的 case_definitions/
case_versions);用例新增 ``test_type`` 与调用关系评判结构后
(见 db/postgresql/changes/),由本层映射为运行时 ``ComparisonCase``。

替换源(测试/本地)可通过 ``set_case_repository`` 注入,不建立第二套
用例维护入口——用例库仍是唯一维护点,本层只读。
"""

from __future__ import annotations

import threading
from typing import Any

from bdlh_runtime.experiments.comparison import CaseRepository, ComparisonCase, ComparisonCaseError
from bdlh_runtime.experiments.judge import CallRelationSpec

_lock = threading.Lock()
_override: CaseRepository | None = None


class DataClientCaseRepository:
    """从 data 服务用例目录构建 ComparisonCase(只读,含内部评判配置)。"""

    def __init__(self, data_client: Any | None = None):
        self._data = data_client

    def _client(self) -> Any:
        if self._data is not None:
            return self._data
        from bdlh_runtime.data_client import DataClient

        return DataClient()

    def list_public_cases(self) -> list[ComparisonCase]:
        from bdlh_runtime.data_client import DataServiceError

        try:
            views = self._client().list_cases()
        except DataServiceError:
            return []
        cases = []
        for view in views:
            case = _case_from_view(view)
            if case is not None:
                cases.append(case)
        return cases

    def get_public_case(self, case_id: str) -> ComparisonCase | None:
        return next((case for case in self.list_public_cases() if case.case_id == case_id), None)

    def public_projection(self) -> list[dict[str, Any]]:
        """公开字段投影(匿名接口/公开 JSON 用):不含评判配置、Mock 返回与 gold。"""
        return [
            {
                "case_id": case.case_id,
                "case_version": case.case_version,
                "title": case.title,
                "message": case.message,
                "scene": case.scene,
                "test_type": "COMPARISON_CASE",
                "allowed_tools": list(case.allowed_tools),
                "default_visible_tools": list(case.default_visible_tools),
                "fixture_set_id": case.fixture_set_id,
            }
            for case in self.list_public_cases()
        ]


def _case_from_view(view: dict[str, Any]) -> ComparisonCase | None:
    """data 服务 /cases 视图 → ComparisonCase。

    视图键为 camelCase(expectedChecks/allowedTools);判定标志是
    expected_checks 内显式的 test_type=COMPARISON_CASE——因历史运行
    外键而被保留的旧用例没有该字段,自然被过滤。
    """
    checks = view.get("expectedChecks") or view.get("checks") or {}
    if checks.get("test_type") != "COMPARISON_CASE":
        return None
    case_id = str(view.get("id") or "")
    allowed = tuple(str(name) for name in view.get("allowedTools") or ())
    if not allowed:
        return None
    default_visible = tuple(
        str(name) for name in checks.get("default_visible_tools") or allowed
    )
    try:
        return ComparisonCase(
            case_id=case_id,
            case_version=int(view.get("version") or 1),
            title=str(view.get("title") or case_id),
            message=str(view.get("message") or ""),
            scene=str(view.get("scene") or "general"),
            allowed_tools=allowed,
            default_visible_tools=default_visible,
            fixture_set_id=str(checks.get("fixture_set_id") or "cmp-fixtures-v1"),
            call_relation=CallRelationSpec.from_payload(
                checks.get("call_relation"),
                known_tools=set(allowed) | set(default_visible),
            ),
            conditions={
                "mock_fixtures": list(checks.get("mock_fixtures") or []),
                "tool_descriptions": dict(checks.get("tool_descriptions") or {}),
                "category": str(checks.get("category") or ""),
                "judge_version": str(checks.get("judge_version") or "call-relation-v1"),
                "fixture_version": checks.get("fixture_set_version") or 1,
                "tool_catalog_version": str(checks.get("tool_catalog_version") or ""),
                "fixture_source_hash": str(checks.get("fixture_source_hash") or ""),
                # 已注册变体与快照(agent_runs 落库外键需要;视图键为 camelCase)
                "case_variants": [
                    {
                        "variant_id": str(v.get("variantId") or ""),
                        "snapshot_id": str(v.get("snapshotId") or ""),
                    }
                    for v in view.get("variants") or []
                    if v.get("variantId")
                ],
            },
        )
    except ComparisonCaseError:
        return None


def set_case_repository(repository: CaseRepository | None) -> None:
    """注入替代仓库(测试用);None 恢复生产实现。"""
    global _override
    with _lock:
        _override = repository


def get_case_repository() -> CaseRepository:
    if _override is not None:
        return _override
    return DataClientCaseRepository()
