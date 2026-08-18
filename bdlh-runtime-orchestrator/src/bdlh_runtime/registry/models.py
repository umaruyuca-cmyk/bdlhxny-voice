"""资格与工具目录的只读记录模型（重写 §3.2/§3.3）。

这些模型只承载从库表加载的行数据，不含任何目录常量——目录真源是
Postgres（生产）或由测试注入 ``InMemoryRegistryStore``。
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
    output_schema: str
    timeout_seconds: int
    cost: int
    enabled: bool
    operations: frozenset[str]
    toolsets: frozenset[str]

    def manifest(self) -> dict[str, object]:
        """给 Agent 菜单用的最小描述；不包含底层路由细节。"""
        return {
            "name": self.name,
            "description": self.description,
            "required_arguments": sorted(self.required_arguments),
            "output_schema": self.output_schema,
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
    side_effects_empty: bool
    # (operation_code, required)；optional 行 required=False
    operations: frozenset[tuple[str, bool]] = frozenset()
    # (capability_name, required)
    capabilities: frozenset[tuple[str, bool]] = frozenset()

    @property
    def declared_operations(self) -> set[str]:
        """required 与 optional 行均并入——只并 required 会让 optional 证
        （如 READ_PUBLIC_RESEARCH）永远进不了有效集合。"""
        return {code for code, _ in self.operations}

    @property
    def declared_capabilities(self) -> set[str]:
        return {name for name, _ in self.capabilities}


@dataclass(frozen=True)
class EntitlementRecord:
    account_id: str  # '*' 表示产品默认
    operation_code: str


@dataclass(frozen=True)
class FastpathRouteRecord:
    name: str
    score_threshold: float
    disposition: str  # RESPOND | BLOCK
    response: str | None
    utterances: tuple[str, ...] = ()


@dataclass(frozen=True)
class BudgetRecord:
    profile: str
    react_round_limit: int
    tool_call_limit: int
    subgraph_timeout_seconds: int
    request_timeout_seconds: int


VALID_TOPICS = ("news", "money_flow", "industry", "web_research")


@dataclass(frozen=True)
class TopicCapabilityRecord:
    """数据主题 → 主题能力的对照（按能力逐条映射，不映射 toolset 整组）。"""

    topic: str
    capability_name: str


@dataclass(frozen=True)
class RegistrySnapshot:
    """启动时加载并通过校验的只读快照。"""

    operations: frozenset[OperationRecord] = frozenset()
    toolsets: frozenset[ToolsetRecord] = frozenset()
    capabilities: frozenset[CapabilityRecord] = frozenset()
    skills: frozenset[SkillRecord] = frozenset()
    runtime_allowlist: frozenset[str] = frozenset()  # operation codes
    entitlements: frozenset[EntitlementRecord] = frozenset()
    fastpath_routes: frozenset[FastpathRouteRecord] = frozenset()
    budgets: frozenset[BudgetRecord] = frozenset()
    topic_capabilities: frozenset[TopicCapabilityRecord] = frozenset()

    def capability(self, name: str) -> CapabilityRecord | None:
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        return None

    def budget_for(self, profile: str) -> BudgetRecord | None:
        for budget in self.budgets:
            if budget.profile == profile:
                return budget
        return None

    def topic_capabilities_for(self, topic: str) -> list[str]:
        return sorted(
            record.capability_name
            for record in self.topic_capabilities
            if record.topic == topic
        )
