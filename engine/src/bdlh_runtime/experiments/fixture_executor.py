"""冻结 Mock 执行器:对比用例与模板运行共用的固定返回执行器。

- Mock 返回按 match_mode(subset/exact) 匹配稳定数据;
- 未命中返回 NOT_IN_FIXTURE;写工具只返回「需要确认」或模拟结果,
  不产生任何外部副作用;
- 工具定义来自冻结目录快照,不构造空 Schema;
- 最终回答始终由真实 LLM 产生,本模块不 Mock 答案。
"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.experiments.fixture_hash import ALLOWED_MOCK_STATUSES


class FrozenFixtureExecutor:
    """按 (工具名, match_mode, 匹配参数) 命中冻结返回;未命中返回 NOT_IN_FIXTURE。"""

    def __init__(self, fixtures: list[dict[str, Any]], *, fixture_version: str | int = 1):
        self._fixtures = list(fixtures or [])
        self._fixture_version = fixture_version
        self.call_records: list[dict[str, Any]] = []

    @staticmethod
    def _matches(fixture: dict[str, Any], arguments: dict[str, Any]) -> bool:
        expected = dict(fixture.get("match_arguments") or {})
        mode = str(fixture.get("match_mode") or "subset")
        if mode == "exact":
            return dict(arguments) == expected
        return all(arguments.get(key) == value for key, value in expected.items())

    async def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        record: dict[str, Any] = {"tool": name, "arguments": dict(arguments)}
        matched = None
        for fixture in self._fixtures:
            tool_name = str(fixture.get("tool") or fixture.get("tool_name") or "")
            if tool_name != name:
                continue
            if self._matches(fixture, arguments):
                matched = fixture
                break
        if matched is None:
            payload = {
                "status": "error",
                "error_code": "NOT_IN_FIXTURE",
                "message": f"工具 {name} 的该组参数没有冻结返回",
                "simulated": True,
            }
        else:
            status = str(matched.get("status") or "success")
            if status not in ALLOWED_MOCK_STATUSES:
                status = "error"
            raw_result = matched.get("result")
            if isinstance(raw_result, dict):
                payload = dict(raw_result)
            else:
                payload = {"value": raw_result}
            payload["status"] = status
            payload["simulated"] = True
            if matched.get("fixture_id"):
                payload["fixture_id"] = str(matched["fixture_id"])
            payload["fixture_version"] = matched.get("fixture_version", self._fixture_version)
        record["status"] = str(payload.get("status") or "success")
        record["result"] = payload
        if payload.get("fixture_id"):
            record["fixture_id"] = payload["fixture_id"]
        if "fixture_version" in payload:
            record["fixture_version"] = payload["fixture_version"]
        self.call_records.append(record)
        return payload
