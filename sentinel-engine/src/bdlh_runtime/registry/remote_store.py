"""Java Data Plane backed, read-only Registry snapshot store（最终八表）。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.infra.remote_runtime_data import RuntimeDataClient

from .models import (
    CapabilityRecord,
    OperationRecord,
    RegistrySnapshot,
    SkillRecord,
    ToolsetRecord,
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
                timeout_seconds=int(row["timeout_seconds"]),
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
                operations=frozenset(skill_operations.get(str(row["skill_id"]), set())),
                capabilities=frozenset(skill_capabilities.get(str(row["skill_id"]), set())),
            )
            for row in _rows(payload, "skills")
        ),
    )
