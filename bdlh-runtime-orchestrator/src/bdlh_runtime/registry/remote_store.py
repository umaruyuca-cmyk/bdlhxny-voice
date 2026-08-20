"""Java Data Plane backed, read-only Registry snapshot store."""

from __future__ import annotations

from typing import Any

from bdlh_runtime.runtime.remote_runtime_data import RuntimeDataClient

from .models import (
    BudgetRecord,
    CapabilityRecord,
    EntitlementRecord,
    FastpathRouteRecord,
    OperationRecord,
    RegistrySnapshot,
    SkillRecord,
    ToolsetRecord,
    TopicCapabilityRecord,
)


class RemoteRegistryStore:
    def __init__(self, client: RuntimeDataClient) -> None:
        self._client = client

    def load(self) -> RegistrySnapshot:
        payload = self._client.call_internal("GET", "/internal/v1/registry/snapshot")
        if not isinstance(payload, dict):
            raise RuntimeError("Java Registry API 返回了非法快照")
        return _snapshot(payload)


def create_remote_registry_store(*, base_url: str, internal_token: str | None) -> RemoteRegistryStore:
    return RemoteRegistryStore(RuntimeDataClient(base_url=base_url, internal_token=internal_token))


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key) or []
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise RuntimeError(f"Java Registry API 字段非法: {key}")
    return value


def _snapshot(payload: dict[str, Any]) -> RegistrySnapshot:
    capability_operations: dict[str, set[str]] = {}
    for row in _rows(payload, "capabilityOperations"):
        capability_operations.setdefault(str(row["capability_name"]), set()).add(str(row["operation_code"]))
    capability_toolsets: dict[str, set[str]] = {}
    for row in _rows(payload, "capabilityToolsets"):
        capability_toolsets.setdefault(str(row["capability_name"]), set()).add(str(row["toolset_name"]))
    skill_operations: dict[str, set[tuple[str, bool]]] = {}
    for row in _rows(payload, "skillOperations"):
        skill_operations.setdefault(str(row["skill_id"]), set()).add(
            (str(row["operation_code"]), bool(row["required"]))
        )
    skill_capabilities: dict[str, set[tuple[str, bool]]] = {}
    for row in _rows(payload, "skillCapabilities"):
        skill_capabilities.setdefault(str(row["skill_id"]), set()).add(
            (str(row["capability_name"]), bool(row["required"]))
        )
    routes = {
        str(row["name"]): FastpathRouteRecord(
            name=str(row["name"]),
            score_threshold=float(row["score_threshold"]),
            disposition=str(row["disposition"]),
            response=row.get("response"),
        )
        for row in _rows(payload, "fastpathRoutes")
    }
    for row in _rows(payload, "fastpathUtterances"):
        route = routes.get(str(row["route_name"]))
        if route is not None:
            routes[route.name] = FastpathRouteRecord(
                name=route.name,
                score_threshold=route.score_threshold,
                disposition=route.disposition,
                response=route.response,
                utterances=route.utterances + (str(row["utterance"]),),
            )
    return RegistrySnapshot(
        operations=frozenset(
            OperationRecord(code=str(row["code"]), description=str(row["description"]))
            for row in _rows(payload, "operations")
        ),
        toolsets=frozenset(
            ToolsetRecord(name=str(row["name"]), description=str(row["description"]))
            for row in _rows(payload, "toolsets")
        ),
        capabilities=frozenset(
            CapabilityRecord(
                name=str(row["name"]),
                description=str(row["description"]),
                domain=str(row["domain"]),
                adapter=str(row["adapter"]),
                read_only=bool(row["read_only"]),
                requires_authenticated_user=bool(row["requires_authenticated_user"]),
                required_arguments=frozenset(row.get("required_arguments") or []),
                depends_on=frozenset(row.get("depends_on") or []),
                output_schema=str(row["output_schema"]),
                timeout_seconds=int(row["timeout_seconds"]),
                cost=int(row["cost"]),
                enabled=bool(row["enabled"]),
                operations=frozenset(capability_operations.get(str(row["name"]), set())),
                toolsets=frozenset(capability_toolsets.get(str(row["name"]), set())),
            )
            for row in _rows(payload, "capabilities")
        ),
        skills=frozenset(
            SkillRecord(
                skill_id=str(row["skill_id"]),
                skill_version=str(row["skill_version"]),
                domain=str(row["domain"]),
                status=str(row["status"]),
                enabled=bool(row["enabled"]),
                side_effects_empty=bool(row["side_effects_empty"]),
                operations=frozenset(skill_operations.get(str(row["skill_id"]), set())),
                capabilities=frozenset(skill_capabilities.get(str(row["skill_id"]), set())),
            )
            for row in _rows(payload, "skills")
        ),
        runtime_allowlist=frozenset(str(row["operation_code"]) for row in _rows(payload, "runtimeAllowlist")),
        entitlements=frozenset(
            EntitlementRecord(account_id=str(row["account_id"]), operation_code=str(row["operation_code"]))
            for row in _rows(payload, "entitlements")
        ),
        fastpath_routes=frozenset(routes.values()),
        budgets=frozenset(
            BudgetRecord(
                profile=str(row["profile"]),
                react_round_limit=int(row["react_round_limit"]),
                tool_call_limit=int(row["tool_call_limit"]),
                subgraph_timeout_seconds=int(row["subgraph_timeout_seconds"]),
                request_timeout_seconds=int(row["request_timeout_seconds"]),
            )
            for row in _rows(payload, "budgets")
        ),
        topic_capabilities=frozenset(
            TopicCapabilityRecord(topic=str(row["topic"]), capability_name=str(row["capability_name"]))
            for row in _rows(payload, "topicCapabilities")
        ),
    )
