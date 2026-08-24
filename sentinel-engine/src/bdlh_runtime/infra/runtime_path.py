"""Cognitive 运行时路径常量与执行进度观察。"""

from __future__ import annotations

from dataclasses import dataclass

COGNITIVE_RUNTIME_PATH = "cognitive_finance"


@dataclass
class CognitiveExecutionProgress:
    """Cognitive 执行进度；仅用于可观测性，不再驱动旧路径回退。"""

    domain_request_started: bool = False
    external_capability_started: bool = False
    persistence_write_started: bool = False
