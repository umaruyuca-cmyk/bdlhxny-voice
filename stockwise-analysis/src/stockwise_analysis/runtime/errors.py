"""运行期错误边界。

节点不应泄露底层 MCP、HTTP 或数据库异常；Adapter 将其转换为结构化错误后，
Root Graph 才能依据预算和降级策略继续或结束。
"""

from __future__ import annotations


class StockWiseRuntimeError(RuntimeError):
    """所有可预期运行期错误的基类。"""


class ConfigurationError(StockWiseRuntimeError):
    """部署配置缺失或不兼容。"""


class RecoverableToolError(StockWiseRuntimeError):
    """可由路由或降级策略处理的外部工具错误。"""
