"""模型/Agent 边界。

Graph 节点只依赖这些接口，不直接绑定某个模型供应商或提示词实现。
"""

from .query_agent import QueryIntent, RuleBasedQueryAgent
from .summary_model import DeterministicSummaryModel

__all__ = ["DeterministicSummaryModel", "QueryIntent", "RuleBasedQueryAgent"]
