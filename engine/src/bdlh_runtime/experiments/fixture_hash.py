"""对比/压缩 Mock fixture 的规范化与内容哈希。

规范化至少包含:工具名、匹配方式、匹配参数、状态、结果、版本。
键排序固定;排除 captured_at 等每次变化字段。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

ALLOWED_MOCK_STATUSES = frozenset({"success", "empty", "timeout", "denied", "stale", "conflict", "error"})
ALLOWED_MATCH_MODES = frozenset({"subset", "exact"})


def _sorted(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted(item) for item in value]
    return value


def normalize_fixture(fixture: dict[str, Any], *, fixture_version: str | int | None = None) -> dict[str, Any]:
    """把一条 Mock 规范成可哈希的稳定结构。"""
    version = fixture_version if fixture_version is not None else fixture.get("fixture_version")
    if version is None:
        version = fixture.get("version") or 1
    match_mode = str(fixture.get("match_mode") or "subset")
    if match_mode not in ALLOWED_MATCH_MODES:
        raise ValueError(f"非法 match_mode:{match_mode!r}")
    status = str(fixture.get("status") or "success")
    if status not in ALLOWED_MOCK_STATUSES:
        raise ValueError(f"非法 Mock 状态:{status!r}")
    payload = {
        "tool": str(fixture.get("tool") or fixture.get("tool_name") or ""),
        "match_mode": match_mode,
        "match_arguments": dict(fixture.get("match_arguments") or {}),
        "status": status,
        "result": fixture.get("result") if fixture.get("result") is not None else {},
        "fixture_version": version,
    }
    if fixture.get("fixture_id"):
        payload["fixture_id"] = str(fixture["fixture_id"])
    return _sorted(payload)


def fixture_content_hash(fixtures: list[dict[str, Any]], *, fixture_version: str | int = 1) -> str:
    """对规范化后的完整 fixture 列表计算 sha256:<hex>。"""
    normalized = [normalize_fixture(row, fixture_version=fixture_version) for row in fixtures]
    canonical = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def catalog_schema_hash(tool_manifests: list[dict[str, Any]]) -> str:
    """对实际发给模型的工具定义摘要计算哈希(顺序敏感)。"""
    canonical = json.dumps(_sorted(tool_manifests), ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
