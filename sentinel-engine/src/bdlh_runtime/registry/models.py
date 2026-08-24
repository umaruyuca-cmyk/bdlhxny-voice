"""资格与工具目录的只读记录模型（最终八表投影）。

资格上限、默认 entitlement、预算与快路径不在本模型；它们来自 Settings / 数据文件。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperationRecord:
    code: str
    description: str


@dataclass(frozen=True)
class ToolsetRecord:
    name: str
    description: str


@dataclass(frozen=True)
class CapabilityRecord:
    name: str
    description: str
    domain: str
    adapter: str  # mcp | java | web | local
    read_only: bool
    requires_authenticated_user: bool
    required_arguments: frozenset[str]
    depends_on: frozenset[str]
    timeout_seconds: int
    enabled: bool
    operations: frozenset[str]
    toolsets: frozenset[str]

    def manifest(self) -> dict[str, object]:
        """给 Agent 菜单用的最小描述；不包含底层路由细节。"""
        return {
            "name": self.name,
            "description": self.description,
            "required_arguments": sorted(self.required_arguments),
            "read_only": self.read_only,
            "toolsets": sorted(self.toolsets),
        }


@dataclass(frozen=True)
class SkillRecord:
    skill_id: str
    skill_version: str
    domain: str
    status: str  # CURRENT | FOUNDATION | EXPERIMENTAL
    enabled: bool
    # (操作证代码, 是否必选)；optional 行 required=False
    operations: frozenset[tuple[str, bool]] = frozenset()
    # (能力名, 是否必选)
    capabilities: frozenset[tuple[str, bool]] = frozenset()

    @property
    def declared_operations(self) -> set[str]:
        """required 与 optional 行均并入——只并 required 会让 optional 证
        （如 READ_PUBLIC_RESEARCH）永远进不了有效集合。"""
        return {code for code, _ in self.operations}

    @property
    def declared_capabilities(self) -> set[str]:
        return {name for name, _ in self.capabilities}


#: 主题字面量（表达用，不发放权限）
VALID_TOPICS = ("news", "money_flow", "industry", "web_research")


@dataclass(frozen=True)
class RegistrySnapshot:
    """启动时加载并通过校验的只读快照（仅八表目录）。"""

    operations: frozenset[OperationRecord] = frozenset()
    toolsets: frozenset[ToolsetRecord] = frozenset()
    capabilities: frozenset[CapabilityRecord] = frozenset()
    skills: frozenset[SkillRecord] = frozenset()

    def capability(self, name: str) -> CapabilityRecord | None:
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        return None
