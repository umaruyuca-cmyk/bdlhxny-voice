"""最终表达模型边界。"""

from __future__ import annotations

from typing import Protocol

from stockwise_analysis.contracts.analysis import AnalysisResult


class SummaryModel(Protocol):
    """将已验证事实转换为用户回答；禁止补造缺失市场数据。"""

    def compose(self, result: AnalysisResult) -> dict:
        """根据结构化 AnalysisResult 生成最终响应。"""


class DeterministicSummaryModel:
    """Phase 0/1 的无模型替身，确保 API 测试不依赖外部大模型。"""

    def compose(self, result: AnalysisResult) -> dict:
        return {
            "status": result.status,
            "analysis_id": result.analysis_id,
            "summary": result.conclusions[0]["text"] if result.conclusions else "暂无结论。",
            "limitations": result.limitations,
        }
