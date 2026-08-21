# ADR-010：Registry 驱动的 Skill 描述与 Domain Dispatcher 契约

> 状态：APPROVED
> 修订：2026-08-17
> 替代内容：编译期 Python Manifest 目录、`accepted_intents`、`analysis_type` 与代码能力映射

## 1. 决策

Domain Dispatcher 保持领域无关，只按 `domain` 将请求交给唯一 Domain Runtime。Skill、Capability、Operation 和 Toolset 的业务目录以 PostgreSQL `registry` schema 为唯一真源，由 Java Data Plane 提供只读 Snapshot API。

Python 中的 `SkillManifest` / `DomainDescriptor` 若继续存在，只能是从 Registry Snapshot 构建的运行时视图，不能保存第二份能力名、Operation、Toolset、启用状态或意图枚举。

## 2. 目标

- 新增 Skill 时不修改 Cognitive 内核路由。
- Skill 启用和能力依赖可由数据库目录审计。
- Domain Dispatcher 不包含金融关键词、Capability 清单或供应商细节。
- Registry 与 Adapter 执行路由在启动时 fail-fast 对账。
- 删除 `analysis_type` 后，不以 `accepted_intents` 或别名恢复类型路由。

## 3. 数据真源

```text
PostgreSQL registry schema
  → Java RegistrySnapshotService
  → GET /internal/v1/registry/snapshot
  → Python RemoteRegistryStore
  → RegistrySnapshot 校验
  → DomainDescriptor / Skill 运行时视图
```

数据库记录：

- Operation
- Toolset
- Capability
- Capability–Operation
- Capability–Toolset
- Skill
- Skill–Operation
- Skill–Capability

Runtime 允许的 Operations、默认 entitlement 和预算是单一配置，不属于 Skill 目录。快路径样句是入口内容数据，也不属于 Skill 目录。

## 4. DomainDescriptor

DomainDescriptor 只允许表达以下运行时信息：

| 字段 | 含义 |
|---|---|
| `domain` | 稳定领域 ID |
| `runtime` | 当前领域执行对象引用 |
| `skills` | 从 Registry Snapshot 投影出的 Skill 只读视图 |
| `result_contracts` | Domain 对外稳定结果契约 |

禁止包含：

- 用户原句分类规则
- `analysis_type` / `accepted_intents`
- 供应商、URL、凭证或 MCP tool 名
- 另一份 Capability、Operation 或 Toolset 描述清单

## 5. Skill 运行时视图

每个 Skill 视图从 Registry 关系表生成：

| 字段 | 来源 |
|---|---|
| `skill_id` / `skill_version` / `domain` / `status` / `enabled` | Skill 表 |
| required / optional Operations | Skill–Operation |
| required / optional Capabilities | Skill–Capability |

业务代码不得声明相同集合。需要静态类型时可以定义通用 Pydantic/dataclass 模型，但实例数据必须来自 Snapshot。

## 6. 启动校验

启动时必须验证：

1. Registry 不为空。
2. Skill 引用的 Operation 和 Capability 全部存在。
3. Capability 至少关联一个 Operation 和 Toolset。
4. `depends_on` 只引用已存在的 Capability。
5. 已启用 Capability 必须只读。
6. Capability 的 Adapter 类型在 Gateway 中有唯一执行处理器。
7. 每个 domain 只能注册一个 Runtime。
8. Registry 或内部 API 不可用时，开发和生产环境拒绝启动。

测试可以显式注入内存 Snapshot；不得因 Java 或 Registry 不可用而自动装配内置业务目录。

## 7. 运行期候选集

```text
effective_operations
  = Runtime 配置
  ∩ 已启用 Skill 声明的 Operations
  ∩ entitlement 配置

eligible
  = 已启用且只读的 Capability
  ∩ 已启用 Skill 声明的 Capability
  ∩ required_operations ⊆ effective_operations

allowed
  = eligible
  ∩ 身份前置条件
  ∩ Provider 可用性
  ∩ Feature Flag
```

用户原句、Goal、`requested_topics[]` 和 LLM 不参与目录或权限计算。

## 8. 实现位置

| 职责 | 当前目标位置 |
|---|---|
| 全量 DDL | `db/postgresql/schema/registry.sql` |
| 初始目录 | `db/postgresql/seed/registry.sql` |
| Java Snapshot | `bdlh-runtime-data/.../registry/RegistrySnapshotService.java` |
| Java API | `bdlh-runtime-data/.../api/RegistryController.java` |
| Python 远程读取 | `bdlh-runtime-orchestrator/.../registry/remote_store.py` |
| Python 校验 | `bdlh-runtime-orchestrator/.../registry/loader.py` |
| 菜单算法 | `bdlh-runtime-orchestrator/.../registry/menu.py` |
| Domain Dispatcher | `bdlh-runtime-orchestrator/.../domains/registry.py` |

应用启动不执行 DDL 或 seed。所有 SQL 只由开发或部署人员按根目录 `db/README.md` 显式执行。

## 9. 被拒绝方案

- Python Manifest 作为编译期目录真源。
- Manifest 与数据库分别维护能力集合后做对账。
- 库空时回退到 `build_default_capability_registry()`。
- 使用 `analysis_type`、`accepted_intents` 或关键词把请求分配给 Skill。
- Domain Dispatcher 根据金融语义挑选工具。
- 应用启动自动建表或写入初始目录。

## 10. 完成标准

- Registry 最终八张表与 Java Snapshot、Python模型一致。
- Python 代码没有业务 Capability/Operation/Skill 清单。
- Manifest/Descriptor 只由 Registry Snapshot 构建。
- `analysis_type` 和 `accepted_intents` 无生产引用。
- 启动校验和 `eligible → allowed` 测试覆盖完整。
- 服务启动路径不存在 DDL、seed 或目录兜底。
