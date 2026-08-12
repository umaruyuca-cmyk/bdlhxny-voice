"""统一能力执行后的数据覆盖检查。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CoverageResult(BaseModel):
    status: Literal["COMPLETE", "PARTIAL", "LIMITED"]
    fulfilled: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)


def evaluate_coverage(
    requirements: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> CoverageResult:
    """关键能力缺失时 LIMITED，可选能力缺失时 PARTIAL。"""

    available = {
        str(item.get("capability"))
        for item in observations
        if item.get("status") in {"SUCCESS", "PARTIAL"} and item.get("capability")
    }
    partial = {
        str(item.get("capability"))
        for item in observations
        if item.get("status") == "PARTIAL" and item.get("capability")
    }
    required = [str(item.get("capability")) for item in requirements if item.get("required", True)]
    optional = [str(item.get("capability")) for item in requirements if not item.get("required", True)]
    missing_required = [name for name in required if name not in available]
    missing_optional = [name for name in optional if name not in available]

    if missing_required:
        status = "LIMITED"
    elif missing_optional or partial:
        status = "PARTIAL"
    else:
        status = "COMPLETE"

    return CoverageResult(
        status=status,
        fulfilled=sorted(available & set(required + optional)),
        missing_required=missing_required,
        missing_optional=missing_optional,
    )
