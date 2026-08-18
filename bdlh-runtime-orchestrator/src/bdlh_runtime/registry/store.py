"""注册表存储：Postgres（生产真源）与内存实现（测试专用）。

生产路径只读 PG；``InMemoryRegistryStore`` 仅供单测注入与种子相同的行，
**禁止**作为生产兜底（重写硬规则 7：库空或校验失败拒绝启动）。
"""

from __future__ import annotations

from typing import Protocol

from .models import (
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


class RegistryStore(Protocol):
    """加载全部目录行的只读接口。"""

    def load(self) -> RegistrySnapshot: ...


class InMemoryRegistryStore:
    """测试用内存仓储；行数据由测试显式插入（与种子一致）。"""

    def __init__(self) -> None:
        self.operations: list[OperationRecord] = []
        self.toolsets: list[ToolsetRecord] = []
        self.capabilities: list[CapabilityRecord] = []
        self.skills: list[SkillRecord] = []
        self.runtime_allowlist: set[str] = set()
        self.entitlements: list[EntitlementRecord] = []
        self.fastpath_routes: list[FastpathRouteRecord] = []
        self.budgets: list[BudgetRecord] = []
        self.topic_capabilities: list[TopicCapabilityRecord] = []

    def load(self) -> RegistrySnapshot:
        return RegistrySnapshot(
            operations=frozenset(self.operations),
            toolsets=frozenset(self.toolsets),
            capabilities=frozenset(self.capabilities),
            skills=frozenset(self.skills),
            runtime_allowlist=frozenset(self.runtime_allowlist),
            entitlements=frozenset(self.entitlements),
            fastpath_routes=frozenset(self.fastpath_routes),
            budgets=frozenset(self.budgets),
            topic_capabilities=frozenset(self.topic_capabilities),
        )


class PostgresRegistryStore:
    """从 Postgres 加载目录行；驱动延迟导入，无 DSN 不得实例化。"""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("PostgresRegistryStore requires POSTGRES_DSN")
        self._dsn = dsn

    def load(self) -> RegistrySnapshot:
        import psycopg.rows

        with self._connect() as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                operations = frozenset(
                    OperationRecord(code=row["code"], description=row["description"])
                    for row in cur.execute("SELECT code, description FROM bdlh_runtime_operation").fetchall()
                )
                toolsets = frozenset(
                    ToolsetRecord(name=row["name"], description=row["description"])
                    for row in cur.execute("SELECT name, description FROM bdlh_runtime_toolset").fetchall()
                )
                raw_caps = cur.execute(
                    "SELECT * FROM bdlh_runtime_capability ORDER BY name"
                ).fetchall()
                cap_ops: dict[str, set[str]] = {}
                for row in cur.execute("SELECT capability_name, operation_code FROM bdlh_runtime_capability_operation").fetchall():
                    cap_ops.setdefault(row["capability_name"], set()).add(row["operation_code"])
                cap_toolsets: dict[str, set[str]] = {}
                for row in cur.execute("SELECT capability_name, toolset_name FROM bdlh_runtime_capability_toolset").fetchall():
                    cap_toolsets.setdefault(row["capability_name"], set()).add(row["toolset_name"])
                capabilities = frozenset(
                    CapabilityRecord(
                        name=row["name"],
                        description=row["description"],
                        domain=row["domain"],
                        adapter=row["adapter"],
                        read_only=row["read_only"],
                        requires_authenticated_user=row["requires_authenticated_user"],
                        required_arguments=frozenset(row["required_arguments"] or ()),
                        depends_on=frozenset(row["depends_on"] or ()),
                        output_schema=row["output_schema"],
                        timeout_seconds=row["timeout_seconds"],
                        cost=row["cost"],
                        enabled=row["enabled"],
                        operations=frozenset(cap_ops.get(row["name"], set())),
                        toolsets=frozenset(cap_toolsets.get(row["name"], set())),
                    )
                    for row in raw_caps
                )
                raw_skills = cur.execute("SELECT * FROM bdlh_runtime_skill").fetchall()
                skill_ops: dict[str, set[tuple[str, bool]]] = {}
                for row in cur.execute("SELECT skill_id, operation_code, required FROM bdlh_runtime_skill_operation").fetchall():
                    skill_ops.setdefault(row["skill_id"], set()).add(
                        (row["operation_code"], bool(row["required"]))
                    )
                skill_caps: dict[str, set[tuple[str, bool]]] = {}
                for row in cur.execute("SELECT skill_id, capability_name, required FROM bdlh_runtime_skill_capability").fetchall():
                    skill_caps.setdefault(row["skill_id"], set()).add(
                        (row["capability_name"], bool(row["required"]))
                    )
                skills = frozenset(
                    SkillRecord(
                        skill_id=row["skill_id"],
                        skill_version=row["skill_version"],
                        domain=row["domain"],
                        status=row["status"],
                        enabled=row["enabled"],
                        side_effects_empty=row["side_effects_empty"],
                        operations=frozenset(skill_ops.get(row["skill_id"], set())),
                        capabilities=frozenset(skill_caps.get(row["skill_id"], set())),
                    )
                    for row in raw_skills
                )
                runtime_allowlist = frozenset(
                    row["operation_code"]
                    for row in cur.execute(
                        "SELECT operation_code FROM bdlh_runtime_runtime_allowlist WHERE runtime_id = 'default'"
                    ).fetchall()
                )
                entitlements = frozenset(
                    EntitlementRecord(account_id=row["account_id"], operation_code=row["operation_code"])
                    for row in cur.execute(
                        "SELECT account_id, operation_code FROM bdlh_runtime_account_entitlement"
                    ).fetchall()
                )
                routes: dict[str, FastpathRouteRecord] = {}
                for row in cur.execute("SELECT * FROM bdlh_runtime_fastpath_route").fetchall():
                    routes[row["name"]] = FastpathRouteRecord(
                        name=row["name"],
                        score_threshold=float(row["score_threshold"]),
                        disposition=row["disposition"],
                        response=row["response"],
                    )
                for row in cur.execute(
                    "SELECT route_name, utterance FROM bdlh_runtime_fastpath_utterance ORDER BY id"
                ).fetchall():
                    base = routes.get(row["route_name"])
                    if base is None:
                        continue
                    routes[row["route_name"]] = FastpathRouteRecord(
                        name=base.name,
                        score_threshold=base.score_threshold,
                        disposition=base.disposition,
                        response=base.response,
                        utterances=base.utterances + (row["utterance"],),
                    )
                budgets = frozenset(
                    BudgetRecord(
                        profile=row["profile"],
                        react_round_limit=row["react_round_limit"],
                        tool_call_limit=row["tool_call_limit"],
                        subgraph_timeout_seconds=row["subgraph_timeout_seconds"],
                        request_timeout_seconds=row["request_timeout_seconds"],
                    )
                    for row in cur.execute("SELECT * FROM bdlh_runtime_run_budget").fetchall()
                )
                topic_capabilities = frozenset(
                    TopicCapabilityRecord(topic=row["topic"], capability_name=row["capability_name"])
                    for row in cur.execute(
                        "SELECT topic, capability_name FROM bdlh_runtime_topic_capability"
                    ).fetchall()
                )
        return RegistrySnapshot(
            operations=operations,
            toolsets=toolsets,
            capabilities=capabilities,
            skills=skills,
            runtime_allowlist=runtime_allowlist,
            entitlements=entitlements,
            fastpath_routes=frozenset(routes.values()),
            budgets=budgets,
            topic_capabilities=topic_capabilities,
        )

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn, autocommit=True)

    def ensure_schema_and_seed(self) -> None:
        """启动时执行 schema.sql 与 seed.sql（幂等）；DDL/seed 文件与
        db/migrations 编号文件内容一致，单一真源以本包内 SQL 为准。"""
        from pathlib import Path

        sql_dir = Path(__file__).parent
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute((sql_dir / "schema.sql").read_text(encoding="utf-8"))
                cur.execute((sql_dir / "seed.sql").read_text(encoding="utf-8"))


def create_registry_store(dsn: str | None) -> RegistryStore:
    """生产工厂：无 DSN 直接失败——禁止内存兜底（硬规则 7）。"""
    if not dsn:
        raise ValueError(
            "registry store requires POSTGRES_DSN; in-memory fallback is forbidden in production paths"
        )
    return PostgresRegistryStore(dsn)
