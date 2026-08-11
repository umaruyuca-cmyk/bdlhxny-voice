"""运行期配置、上下文、预算与恢复能力。"""

from .context import RunContext

__all__ = ["RunContext", "StockWiseApplication", "create_application"]


def __getattr__(name: str):
    """按需加载 Application，避免 runtime.budgets 导入触发循环依赖。"""
    if name in {"StockWiseApplication", "create_application"}:
        from .application import StockWiseApplication, create_application

        return {"StockWiseApplication": StockWiseApplication, "create_application": create_application}[name]
    raise AttributeError(name)
