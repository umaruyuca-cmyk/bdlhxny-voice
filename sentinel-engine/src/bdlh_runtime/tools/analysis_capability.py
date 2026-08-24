"""Analysis Engine 的可替换能力边界。

Finance Runtime 只依赖 ``AnalysisCapabilityAdapter``，不依赖本地函数、HTTP 或
独立 Skill 的部署方式。未来把分析计算迁移到远程服务时，只需要替换工厂
返回的实现，不需要改动编排与状态契约。
"""

from __future__ import annotations

from typing import Protocol

from bdlh_runtime.contracts.analysis import AnalysisInput, AnalysisResult


class AnalysisCapabilityAdapter(Protocol):
    """分析能力适配器（Adapter，适配层）协议。"""

    def analyze(self, analysis_input: AnalysisInput) -> AnalysisResult:
        """根据标准化输入执行确定性分析并返回结构化结果。"""
        ...


class PythonAnalysisCapabilityAdapter:
    """当前默认实现：调用本地 Python Analysis Engine。"""

    def analyze(self, analysis_input: AnalysisInput) -> AnalysisResult:
        from bdlh_runtime.compute.analysis_engine import analyze

        return analyze(analysis_input)


def create_analysis_capability() -> AnalysisCapabilityAdapter:
    """创建分析能力实现；未来可替换为 HTTP/MCP/Skill Adapter。"""
    return PythonAnalysisCapabilityAdapter()
