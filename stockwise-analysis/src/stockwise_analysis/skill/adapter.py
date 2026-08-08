"""可选独立分析能力的适配边界。"""

from __future__ import annotations

from typing import Protocol

from stockwise_analysis.contracts.analysis import AnalysisInput, AnalysisResult


class AnalysisCapabilityAdapter(Protocol):
    """可替换 Python 本地实现、子进程或未来独立 Skill 服务。"""

    async def analyze(self, analysis_input: AnalysisInput) -> AnalysisResult:
        """只执行纯分析，禁止查询 MCP、Java、数据库或行情接口。"""
