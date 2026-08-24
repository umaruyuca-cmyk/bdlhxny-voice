"""Data-quality 时点规则：时效与 Provenance 深度（架构 §11.3）。

领域无关：只扫结构化字典，不访问外部系统、不调用 LLM。
"""

from __future__ import annotations

from typing import Any

_STALE_FRESHNESS = frozenset({"STALE", "EXPIRED", "TOO_OLD"})
_OBS_OK_STATUS = frozenset({"SUCCESS", "PARTIAL"})


def evaluate_freshness(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    """任一节点标记 STALE / 过期新鲜度 → 阻断。"""

    for node in _walk_dicts(payload):
        quality = node.get("data_quality")
        if isinstance(quality, dict):
            status = str(quality.get("quality_status") or "").upper()
            freshness = str(quality.get("freshness") or "").upper()
            if status == "STALE" or freshness in _STALE_FRESHNESS:
                return (
                    "DATA_STALE",
                    "DATA-FRESHNESS-001",
                    "数据已过期或标记为陈旧，不能支撑当前结论",
                )
        freshness_direct = str(node.get("freshness") or "").upper()
        if freshness_direct in _STALE_FRESHNESS:
            return (
                "DATA_STALE",
                "DATA-FRESHNESS-001",
                "数据已过期或标记为陈旧，不能支撑当前结论",
            )
    return None


def evaluate_provenance_depth(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    """Observation 形态节点必须带可审计 provenance（source/tool/retrieved_at）。"""

    for node in _walk_dicts(payload):
        if not _is_observation_like(node):
            continue
        status = str(node.get("status") or "SUCCESS").upper()
        if status not in _OBS_OK_STATUS:
            continue
        provenance = node.get("provenance")
        if not isinstance(provenance, list) or not provenance:
            return (
                "PROVENANCE_REQUIRED",
                "DATA-PROVENANCE-001",
                "成功或部分成功的观测缺少可追溯 provenance",
            )
        for record in provenance:
            if not isinstance(record, dict):
                return (
                    "PROVENANCE_INCOMPLETE",
                    "DATA-PROVENANCE-002",
                    "provenance 记录必须是结构化对象",
                )
            source = str(record.get("source") or "").strip()
            tool = str(record.get("tool") or "").strip()
            retrieved_at = str(record.get("retrieved_at") or "").strip()
            if not source or not tool or not retrieved_at:
                return (
                    "PROVENANCE_INCOMPLETE",
                    "DATA-PROVENANCE-002",
                    "provenance 必须包含 source、tool 与 retrieved_at",
                )
    return None


def _is_observation_like(node: dict[str, Any]) -> bool:
    if "observation_id" in node and "capability" in node:
        return True
    return "capability" in node and "status" in node and "data_quality" in node


def _walk_dicts(payload: Any):
    stack: list[Any] = [payload]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
