"""资格与工具目录真源（最终八表 + 配置层资格）。

目录只在数据库（生产 Postgres）；代码只留算法与执行，禁止内置第二份
工具清单兜底。测试用 ``InMemoryRegistryStore`` 注入与种子相同的行。
"""

from .defaults import (
    DEFAULT_ENTITLEMENT_OPERATIONS,
    DEFAULT_RUNTIME_ALLOWED_OPERATIONS,
)
from .loader import load_and_validate
from .menu import (
    FEATURE_GATED_CAPABILITIES,
    allowed_capabilities,
    apply_feature_gates,
    dependency_closure,
    effective_operations,
    eligible_capabilities,
    enabled_skills,
)
from .models import (
    VALID_TOPICS,
    CapabilityRecord,
    OperationRecord,
    RegistrySnapshot,
    SkillRecord,
    ToolsetRecord,
)
from .remote_store import RemoteRegistryStore, create_remote_registry_store
from .store import (
    InMemoryRegistryStore,
    RegistryStore,
)

__all__ = [
    "DEFAULT_ENTITLEMENT_OPERATIONS",
    "DEFAULT_RUNTIME_ALLOWED_OPERATIONS",
    "VALID_TOPICS",
    "CapabilityRecord",
    "InMemoryRegistryStore",
    "OperationRecord",
    "RemoteRegistryStore",
    "RegistrySnapshot",
    "RegistryStore",
    "SkillRecord",
    "ToolsetRecord",
    "FEATURE_GATED_CAPABILITIES",
    "allowed_capabilities",
    "apply_feature_gates",
    "create_remote_registry_store",
    "dependency_closure",
    "effective_operations",
    "eligible_capabilities",
    "enabled_skills",
    "load_and_validate",
]
