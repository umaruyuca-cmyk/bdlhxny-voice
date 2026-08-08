"""分析能力注册边界。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisCapabilitySpec:
    """记录可用分析能力的版本和部署形态。"""

    name: str
    implementation: str
    methodology_version: str
