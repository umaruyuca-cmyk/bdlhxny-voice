"""AnalysisResult 契约校验。"""

from __future__ import annotations

from stockwise_analysis.contracts.analysis import AnalysisResult


def validate_analysis_result(result: AnalysisResult) -> AnalysisResult:
    """通过 Pydantic 重新校验并返回标准化结果。"""

    return AnalysisResult.model_validate(result)
