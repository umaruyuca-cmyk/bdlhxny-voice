"""运行期错误边界。

节点与 Adapter 将底层 MCP/HTTP/数据库异常转换为结构化错误，供 Cognitive
编排按预算与防护策略继续或结束。
"""

from __future__ import annotations


class AgentRuntimeError(RuntimeError):
    """所有可预期运行期错误的基类。"""


class ConfigurationError(AgentRuntimeError):
    """部署配置缺失或不兼容。"""
