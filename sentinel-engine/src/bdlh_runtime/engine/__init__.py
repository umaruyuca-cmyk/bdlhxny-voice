"""Agent 引擎：原生 tool calling 循环与 scoped / search 装载（设计文档 §4.2、§4.3）。"""

from .executor import CatalogToolExecutor
from .loader import SCENE_TOOLSETS, ToolLoader
from .loop import AgentLoop, AgentResult, AgentTurn
from .runtime import EngineRuntime

__all__ = [
    "AgentLoop",
    "AgentResult",
    "AgentTurn",
    "CatalogToolExecutor",
    "EngineRuntime",
    "SCENE_TOOLSETS",
    "ToolLoader",
]
