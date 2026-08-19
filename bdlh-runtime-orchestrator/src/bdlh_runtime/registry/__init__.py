"""资格与工具目录真源（重写：入口理解与资格菜单）。

目录只在数据库（生产 Postgres）；代码只留算法与执行，禁止内置第二份
工具清单兜底。测试用 ``InMemoryRegistryStore`` 注入与种子相同的行。
"""

from .loader import load_and_validate
from .menu import (
    FLAT_WINDOW_LIMIT,
    FEATURE_GATED_CAPABILITIES,
    ToolWindow,
    allowed_capabilities,
    apply_feature_gates,
    build_window,
    dependency_closure,
    effective_operations,
    eligible_capabilities,
    enabled_skills,
)
from .models import (
    VALID_TOPICS,
    BudgetRecord,
    CapabilityRecord,
    EntitlementRecord,
    FastpathRouteRecord,
    OperationRecord,
    RegistrySnapshot,
    SkillRecord,
    ToolsetRecord,
    TopicCapabilityRecord,
)
from .store import (
    InMemoryRegistryStore,
    PostgresRegistryStore,
    RegistryStore,
    create_registry_store,
)

__all__ = [
    "FLAT_WINDOW_LIMIT",
    "VALID_TOPICS",
    "BudgetRecord",
    "CapabilityRecord",
    "EntitlementRecord",
    "FastpathRouteRecord",
    "InMemoryRegistryStore",
    "OperationRecord",
    "PostgresRegistryStore",
    "RegistrySnapshot",
    "RegistryStore",
    "SkillRecord",
    "ToolWindow",
    "ToolsetRecord",
    "TopicCapabilityRecord",
    "FEATURE_GATED_CAPABILITIES",
    "allowed_capabilities",
    "apply_feature_gates",
    "build_window",
    "create_registry_store",
    "dependency_closure",
    "effective_operations",
    "eligible_capabilities",
    "enabled_skills",
    "load_and_validate",
]
