"""运行期配置、上下文与应用装配。"""

from .context import RunContext

__all__ = ["RunContext", "AgentRuntimeApplication", "create_application"]


def __getattr__(name: str):
    """按需加载 Application，避免循环导入。"""
    if name in {"AgentRuntimeApplication", "create_application"}:
        from .application import AgentRuntimeApplication, create_application

        return {"AgentRuntimeApplication": AgentRuntimeApplication, "create_application": create_application}[name]
    raise AttributeError(name)
