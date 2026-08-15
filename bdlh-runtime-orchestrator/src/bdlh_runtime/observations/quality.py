"""Observation 数据质量判断工具。"""

from __future__ import annotations

from bdlh_runtime.contracts.observation import DataQuality, Observation


def merge_quality(observations: list[Observation]) -> DataQuality:
    """聚合多个 Observation 的完整度与可用状态。"""

    if not observations:
        return DataQuality(completeness=0.0, quality_status="INVALID")
    completeness = sum(item.data_quality.completeness for item in observations) / len(observations)
    status = "OK" if all(item.data_quality.quality_status == "OK" for item in observations) else "PARTIAL"
    unavailable = [item.capability for item in observations if item.status == "UNAVAILABLE"]
    return DataQuality(completeness=completeness, quality_status=status, known_unavailable=unavailable)
