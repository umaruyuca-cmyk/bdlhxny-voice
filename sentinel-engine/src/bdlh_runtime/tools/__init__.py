"""Controlled tools and capability views for the Cognitive runtime.

Capability 目录真源是数据库（RegistrySnapshot）；本模块导出派生视图构建器，
不提供默认清单兜底。
"""

from .capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    ToolsetName,
    load_capability_registry,
    registry_from_snapshot,
)

__all__ = [
    "CapabilityRegistry",
    "CapabilitySpec",
    "ToolsetName",
    "load_capability_registry",
    "registry_from_snapshot",
]
