# BDLH 入口理解与资格菜单全量重写实施 Prompt

> 文档状态：当前专项实施 Prompt  
> 日期：2026-08-17  
> 适用阶段：全量替换（关闭全局实施 Prompt 缺口 **G2**）  
> 全局约束：必须遵守 [00-BDLH-Agent-Runtime生产开发实施Prompt.md](./00-BDLH-Agent-Runtime生产开发实施Prompt.md) 的 **§2 生产唯一运行标准**（无开发/生产双轨产品路径）  
> 需求真源：`C:\Users\win\Desktop\BDLH-语义路由与工具菜单-需求更新-v2.md`

本任务一次性完成入口理解、Registry 目录和能力菜单重写。不得保留 `analysis_type`、旧三模式路由、内置目录、ToolWindow、双写或旧数据库结构。本任务**不**关闭 ADR-014 真 checkpoint（缺口 G1）；但不得引入依赖假恢复或 mock 降级的新路径。

## 0. 调用参数

```text
TASK=REWRITE_ENTRY_AND_TOOL_MENU
WORKSPACE=D:\bdlh-agent\bdlhxny-agent
DATABASE_MODE=EMPTY_DATABASE_FULL_SCHEMA
REAL_INFRA_VALIDATION=false
COMMIT=false
PUSH=false
```

除非调用方明确覆盖，禁止连接真实数据库、提交或推送。

## 1. 最终运行路径

```text
用户请求
  → Turn Router / 身份 / 只读门控
  → Semantic Router 快路径
       命中 chitchat / knowledge / forbidden → RESPOND 或 BLOCK
       未命中 → Understand
  → Understand → goals[] / entities / constraints / missing / needs_external
       missing 非空 → ASK_USER
       needs_external=false → RESPOND
       needs_external=true → 构建 eligible → allowed
  → Agent 每轮从 allowed 选择 CALL_TOOL 或建议 FINISH
  → Gateway 再校验并执行，Observation 写回
  → GoalCoverage 决定继续、ASK_USER、PARTIAL 或 COMPLETE
```

理解阶段不得输出 `route`、`skill_id`、`analysis_type` 或 `plan_steps`。Agent 的 `FINISH` 只是建议，最终完成状态由 GoalCoverage 判定。

## 2. 五个核心概念

| 名称 | 当前定义 |
|---|---|
| `goals[]` | 本轮要完成的可验证任务单元，不是类别或工具名 |
| Operation | 产品授予的能力资格，例如 `READ_MARKET_DATA` |
| Capability | 可执行能力，例如 `market.get_realtime_quote` |
| `eligible` | Runtime、已启用 Skill、entitlement 和只读规则允许出现的能力全集 |
| `allowed` | `eligible` 中满足本轮认证状态和 Provider 可用性的合法调用全集 |

用户原句、`requested_topics[]`、Goal 和 LLM 均不得参与资格发放。

## 3. 数据库唯一真源

### 3.1 所有权

- Registry 数据由 Java Data Plane 所有，位于 PostgreSQL `registry` schema。
- 全量 DDL 只允许放在 `db/postgresql/schema/registry.sql`。
- 全量目录种子只允许放在 `db/postgresql/seed/registry.sql`。
- SQL 由开发或部署人员显式执行；任何应用启动流程都不得执行 DDL 或 seed。
- Orchestrator 不持有 PostgreSQL DSN，不使用 psycopg/SQLAlchemy 读取 Registry。
- Java Data Plane 通过 `/internal/v1/registry/snapshot` 提供只读快照。
- Orchestrator 通过 `RemoteRegistryStore` 加载快照，加载失败或校验失败时拒绝启动。

### 3.2 最终八张表

Registry 只保留以下八张目录表：

1. `bdlh_runtime_operation`
2. `bdlh_runtime_toolset`
3. `bdlh_runtime_capability`
4. `bdlh_runtime_capability_operation`
5. `bdlh_runtime_capability_toolset`
6. `bdlh_runtime_skill`
7. `bdlh_runtime_skill_operation`
8. `bdlh_runtime_skill_capability`

直接从全量 schema 删除：

- `bdlh_runtime_runtime_allowlist`
- `bdlh_runtime_account_entitlement`
- `bdlh_runtime_run_budget`
- `bdlh_runtime_fastpath_route`
- `bdlh_runtime_fastpath_utterance`
- `bdlh_runtime_topic_capability`

直接从目录字段删除：

- `Capability.analysis_types`
- `Capability.cost`
- `Capability.output_schema`
- `Skill.side_effects_empty`

Runtime 资格上限、默认 entitlement 和默认预算改为单一配置；快路径样句改为 Python 数据文件。它们不是能力目录，不在数据库和业务算法中复制第二份。

### 3.3 种子规则

- seed 是新项目完整初始目录，不使用 `ON CONFLICT DO NOTHING` 承担旧库合并。
- seed 只引用最终八张表和最终字段。
- `stock-research` 默认启用；`portfolio-health`、`suitability-evaluation` 默认关闭。
- `plugin-contract-probe` 和 `plugin_probe.run_contract_check` 不进入当前业务种子。
- `research.deep_search` 是否登记由 ADR-016 当前决定；本任务不修改其内部执行策略。

## 4. 配置和快路径

配置层只保留一份：

```text
RUNTIME_ALLOWED_OPERATIONS
DEFAULT_ENTITLEMENT_OPERATIONS
DEFAULT_REACT_ROUND_LIMIT
DEFAULT_TOOL_CALL_LIMIT
DEFAULT_SUBGRAPH_TIMEOUT_SECONDS
DEFAULT_REQUEST_TIMEOUT_SECONDS
```

快路径样句放在 `cognitive/semantic_router/fastpath_data.py`，只包含：

- `chitchat`
- `knowledge`
- `forbidden`

快路径未命中或编码失败时进入 Understand，不生成工具名单。

## 5. 菜单算法

```text
effective_operations
  = Runtime 允许的 Operations
  ∩ 已启用 Skill 声明的 Operations
  ∩ 默认 entitlement

eligible
  = 已启用 Capability
  ∩ 只读 Capability
  ∩ 属于已启用 Skill
  ∩ required_operations ⊆ effective_operations

allowed
  = eligible
  ∩ 当前认证状态满足 requires_authenticated_user
  ∩ 当前 Provider 可用
  ∩ 当前 Feature Flag 允许
```

硬规则：

- `allowed` 是交给 Agent 的唯一扁平菜单。
- 不实现 `ToolWindow`、`OPEN_TOOLSET`、`EXPAND_WINDOW`、`generation` 或 Toolset 向量排序。
- 缺少调用参数不会从 `allowed` 删除能力；由 `depends_on` 闭包补受控前置能力。
- Gateway 执行前必须再次校验 `capability ∈ allowed`、身份和参数。

## 6. 契约

`GoalSpec` 至少包含：

```text
goal_id
objective
requested_topics[]
success_criteria[]
status                 # PENDING | COVERED | BLOCKED
observation_refs[]
```

`UnderstandOutput` 至少包含：

```text
goals[]
entities[]
constraints[]
missing[]
needs_external
```

`requested_topics[]` 只用于表达数据主题，不发放权限、不缩小 `allowed`，不得替代已经删除的 `analysis_type`。

## 7. 代码修改范围

### 7.1 Java Data Plane

- 修改 `db/postgresql/schema/registry.sql` 和 `db/postgresql/seed/registry.sql` 为最终结构。
- 修改 `RegistrySnapshotService`，只查询最终八张表和最终字段。
- 修改 `RegistryController` 契约测试，快照不再返回已删除的数据组和字段。
- Java 启动不执行建表或种子。

### 7.2 Orchestrator Registry

- `registry/models.py` 删除 Budget、Entitlement、FastpathRoute、TopicCapability 以及已删字段模型。
- `registry/remote_store.py` 只解析 Java 最终快照。
- `registry/loader.py` 只校验最终目录引用、只读约束和空目录拒启。
- `registry/menu.py` 保留 `effective_operations`、`eligible_capabilities`、`allowed_capabilities` 和依赖闭包；删除窗口模型与窗口构建。
- `registry/store.py` 只保留测试显式注入的最终快照替身，不得成为开发启动兜底。

### 7.3 Cognitive 与 Finance

- 从 contracts、state、planner、manifest、authorization、idempotency、API 和测试中物理删除 `analysis_type`。
- 理解输出改为 Goal 模型，不做类型路由和固定工具计划。
- `CognitiveOrchestrator` 只使用远程 Registry 快照与配置构建权限上下文。
- Finance 只根据 Goal、Observation 和明确授权运行，不按金融类型字符串分支选工具。
- 删除任何 `build_default_capability_registry`、硬编码能力映射和目录兜底。
- Manifest/Descriptor 作为从 Registry 投影出的运行时描述，不再保存第二份能力和 Operation 清单。

### 7.4 应用装配

```text
1. 读取 Settings
2. 探测 Java Data Plane
3. RemoteRegistryStore 调用 Java Snapshot API
4. 校验 Registry Snapshot
5. 加载快路径数据文件
6. 装配 Menu / Gateway / Cognitive / Finance / FastAPI
```

任一步关键配置或目录校验失败都拒绝启动。不得创建表、写 seed 或改用内置目录。

## 8. 明确删除

- `analysis_type` 的所有字段、枚举、映射、分支、幂等键和测试 fixture
- `IntentRoute` 的三模式业务分流
- `REQUIREMENT_POLICIES[analysis_type]`
- `ANALYSIS_BUDGETS` 与 `budget_for(analysis_type)`
- ToolWindow 及其所有呈现动作
- Python 内置 Capability/Skill/Operation 目录
- Orchestrator 内的 schema、seed 和 PostgreSQL Registry 访问
- 已删除 Registry 表与字段对应的 Java/Python DTO
- 为旧契约保留的别名、投影、双写和读取兜底

## 9. 验收清单

- [ ] Orchestrator 生产源码和当前测试中搜索 `analysis_type` 为零
- [ ] 搜索 `ToolWindow|OPEN_TOOLSET|EXPAND_WINDOW` 为零
- [ ] 搜索已删除六张 Registry 表名，仅允许出现在历史归档
- [ ] 搜索 `build_default_capability_registry` 无生产引用
- [ ] Orchestrator 无 Registry PostgreSQL 驱动或直接 SQL
- [ ] 服务启动路径无 `CREATE TABLE`、schema 执行或 seed 执行
- [ ] Java Snapshot 只返回最终八张表对应的目录数据
- [ ] 空 Registry 或非法引用导致启动失败
- [ ] `eligible` 不读取用户原句、Goal 或 `requested_topics`
- [ ] 未登录时，要求认证的能力不进入 `allowed`
- [ ] Agent 选择 `allowed` 外能力时 Gateway 拒绝
- [ ] `depends_on` 能确定性补齐标的解析等前置步骤
- [ ] Goal 无 Observation 覆盖时，模型建议 `FINISH` 也不能结束
- [ ] Orchestrator、Java Data Plane 和 Memory Service 测试通过

## 10. 完成报告格式

```text
# 入口与菜单全量重写结果

## 删除的旧结构
## 最终数据库结构
## Java Data Plane Registry API
## eligible → allowed 权限链
## Goal 与停止条件
## 静态残留扫描
## 测试结果
## 未完成事项
```
