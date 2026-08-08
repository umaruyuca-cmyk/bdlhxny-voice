"""Stable contracts exchanged between workflow nodes and integrations."""

from .analysis import AnalysisInput, AnalysisResult
from .data_requirements import DataRequirement
from .observation import Observation
from .workflow import TaskSpec, WorkflowPlan

__all__ = [
    "AnalysisInput",
    "AnalysisResult",
    "Observation",
    "DataRequirement",
    "TaskSpec",
    "WorkflowPlan",
]
