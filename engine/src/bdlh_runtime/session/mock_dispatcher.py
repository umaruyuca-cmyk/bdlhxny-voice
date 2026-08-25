"""按 gold.runtime_mock_fixtures 返回冻结结果的 Mock 工具调度器。

gold 的合法用途之一就是"配置冻结 Mock 返回"(使用说明 §8):只有 Agent
正确调用工具后,调度器才返回匹配的冻结结果;路径/参数不匹配一律返回
``FILE_NOT_IN_FIXTURE``,绝不把正确内容当兜底返回——否则参数错误和
工具选择错误无法被统计。

所有返回都标记 simulated,不得对外冒充真实 API 延迟或数据。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

ERROR_NOT_IN_FIXTURE = "TOOL_NOT_IN_FIXTURE"


@dataclass
class MockCallRecord:
    step: int
    tool_name: str
    arguments: dict[str, Any]
    matched_fixture_id: str | None
    status: str
    payload: dict[str, Any]
    simulated: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "fixture_id": self.matched_fixture_id,
            "status": self.status,
            "result": self.payload,
            "simulated": self.simulated,
        }


@dataclass
class SessionMockDispatcher:
    """fixture 匹配:精确参数子集匹配 → fallback 错误 → TOOL_NOT_IN_FIXTURE。"""

    fixtures: tuple[dict[str, Any], ...]
    call_log: list[MockCallRecord] = field(default_factory=list)
    _step: int = field(default=0)

    async def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._step += 1
        matched = self._match(name, arguments)
        if matched is None:
            fallback = self._fallback(name)
            payload = fallback if fallback is not None else self._not_in_fixture(name)
            fixture_id = None
            status = "error"
        else:
            fixture_id = str(matched.get("fixture_id"))
            status = str(matched.get("status") or "success")
            payload = self._payload(matched)
        self.call_log.append(
            MockCallRecord(
                step=self._step,
                tool_name=name,
                arguments=dict(arguments),
                matched_fixture_id=fixture_id if matched is not None else None,
                status=status,
                payload=payload,
            )
        )
        return payload

    def _match(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        for fixture in self.fixtures:
            if str(fixture.get("tool_name")) != name:
                continue
            if str(fixture.get("match") or "") == "fallback":
                continue
            match_arguments = fixture.get("match_arguments") or {}
            if all(arguments.get(key) == value for key, value in match_arguments.items()):
                return fixture
        return None

    def _fallback(self, name: str) -> dict[str, Any] | None:
        for fixture in self.fixtures:
            if str(fixture.get("tool_name")) == name and str(fixture.get("match") or "") == "fallback":
                return {
                    "status": "error",
                    "error_code": str(fixture.get("error_code") or ERROR_NOT_IN_FIXTURE),
                    "message": str((fixture.get("result") or {}).get("message") or "该调用不匹配任何冻结 fixture。"),
                    "simulated": True,
                }
        return None

    @staticmethod
    def _not_in_fixture(name: str) -> dict[str, Any]:
        return {
            "status": "error",
            "error_code": ERROR_NOT_IN_FIXTURE,
            "message": f"工具 {name} 的该组参数不在本用例冻结 fixture 集内。",
            "simulated": True,
        }

    @staticmethod
    def _payload(fixture: dict[str, Any]) -> dict[str, Any]:
        result = dict(fixture.get("result") or {})
        if str(fixture.get("status") or "success") == "error":
            return {
                "status": "error",
                "error_code": str(fixture.get("error_code") or "MOCK_ERROR"),
                "simulated": True,
                **result,
            }
        payload: dict[str, Any] = {"status": "success", "simulated": True, **result}
        return payload


def load_gold(path) -> dict[str, Any]:
    """读取 gold(仅 Mock 调度器与评测器允许调用)。"""

    from pathlib import Path

    return json.loads(Path(path).read_text(encoding="utf-8"))


def dispatcher_from_gold(gold: dict[str, Any]) -> SessionMockDispatcher:
    return SessionMockDispatcher(fixtures=tuple(gold.get("runtime_mock_fixtures") or ()))
