"""工作流节点与集成层之间交换的稳定契约。"""

from .analysis import AnalysisInput, AnalysisResult
from .data_requirements import DataRequirement
from .observation import Observation

__all__ = [
    "AnalysisInput",
    "AnalysisResult",
    "Observation",
    "DataRequirement",
]
