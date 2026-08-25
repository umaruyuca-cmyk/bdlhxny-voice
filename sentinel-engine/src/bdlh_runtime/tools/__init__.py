"""工具包：Capability 视图 + 统一工具目录（ToolCard）。

Capability 目录真源是数据库（RegistrySnapshot）；T2 起对外以 ``ToolCatalog``
为唯一真源（装载器 / 检索索引 / 治理中间件均从目录读取）。本模块导出两者，
不提供默认清单兜底。
"""

from .capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    ToolsetName,
    load_capability_registry,
    registry_from_snapshot,
)
from .catalog import (
    CostHint,
    ToolCard,
    ToolCatalog,
    ToolOrigin,
    catalog_from_snapshot,
    register_mcp_tool,
)

__all__ = [
    "CapabilityRegistry",
    "CapabilitySpec",
    "CostHint",
    "ToolCard",
    "ToolCatalog",
    "ToolOrigin",
    "ToolsetName",
    "catalog_from_snapshot",
    "load_capability_registry",
    "register_mcp_tool",
    "registry_from_snapshot",
]
