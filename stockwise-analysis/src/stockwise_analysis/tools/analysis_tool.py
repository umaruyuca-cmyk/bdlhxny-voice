"""分析能力工具封装。

把 domain/analysis_engine.analyze 包装为 ToolRegistry 可注册的只读工具，
让 Agent（Research/Summary）能按统一工具名调用分析能力。分析能力本身是
纯函数，不查询外部数据——本工具只是提供一层注册/调用边界。

生产环境若把分析能力迁移为独立 Skill 服务，只需替换本文件的 handler
实现（改调 HTTP/进程），工具名和契约不变——这是"部署形态后置"的体现。
"""

from __future__ import annotations

import logging
from typing import Any

from stockwise_analysis.contracts.analysis import AnalysisInput

from .analysis_capability import create_analysis_capability
from .registry import ToolRegistry

logger = logging.getLogger("stockwise_analysis.tools.analysis")


def _analyze_handler(args: dict[str, Any]) -> dict[str, Any]:
    """Tool handler：接收 AnalysisInput dict，返回 AnalysisResult dict。

    args 即 AnalysisInput 的 model_dump()。缺 analysis_id/analysis_type 时
    用安全默认值兜底，避免工具层抛未捕获异常。
    """

    try:
        analysis_input = AnalysisInput.model_validate(args)
        result = create_analysis_capability().analyze(analysis_input)
        return result.model_dump()
    except Exception as exc:
        logger.error("分析工具调用失败: %s", exc)
        return {
            "status": "FAILED",
            "analysis_id": str(args.get("analysis_id", "unknown")),
            "facts": [],
            "calculated_indicators": {},
            "signals": [],
            "risk_flags": [],
            "conclusions": [],
            "limitations": [f"分析引擎异常: {exc}"],
        }


def register_analysis_tools(registry: ToolRegistry) -> ToolRegistry:
    """把分析能力注册进 ToolRegistry。

    注册工具名：analysis.run_analysis。只读工具，不允许写操作。
    """

    registry.register(
        "analysis.run_analysis",
        "Run deterministic financial analysis on standardized AnalysisInput. "
        "Input must be a valid AnalysisInput dict with historical_prices bars. "
        "Returns AnalysisResult with indicators, signals, risk flags.",
        _analyze_handler,
        read_only=True,
        timeout_seconds=60,  # 指标计算可能涉及较多数据点
    )
    return registry
