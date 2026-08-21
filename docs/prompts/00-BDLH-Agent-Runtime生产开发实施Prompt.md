# BDLH Agent Runtime 开发实施 Prompt

> 文档状态：当前全局实施基线（与统一生产架构对齐）  
> 日期：2026-08-17  
> 适用阶段：实现与联调；**运行时行为一律按生产标准，不再维护「开发宽松 / 生产严格」双轨产品路径**

本文是执行者的全局指令。架构决策仍以 [统一生产架构](../architecture/00-BDLH-Agent-Runtime统一生产架构.md) 与已批准 ADR 为准；本文负责：**唯一运行标准、权威阅读顺序、完成定义、相对架构的未完成清单**。

## 0. 使用方式

执行任务时必须同时提供明确的 `TASK`、范围和验收条件。若存在专项 Prompt，以专项 Prompt 细化本文件，但不得违反本文件的全局边界。

当前专项 Prompt：

- [01-入口理解与资格菜单重写-实施Prompt.md](./01-入口理解与资格菜单重写-实施Prompt.md)：入口理解、删除 `analysis_type`、数据库目录真源、`eligible → allowed` 和 Goal Coverage。

历史评审、阶段实施报告和 Git 历史只用于解释过去，不是执行依据。

## 1. 权威来源

冲突时按以下顺序处理：

1. 安全、身份、隐私和只读边界；
2. [统一生产架构](../architecture/00-BDLH-Agent-Runtime统一生产架构.md)；
3. 已批准且未被后续决策替代的 ADR；
4. 本文件与当前专项 Prompt；
5. 当前代码和测试体现的实现事实（若与上列冲突，按上列改代码与测试，不保留双轨）；
6. 历史报告和归档文档。

发现低优先级材料与高优先级材料冲突时，直接按高优先级目标全量修改，不添加适配层。

## 2. 生产唯一运行标准（强制）

### 2.1 不再按环境降低产品行为

| 允许 | 禁止 |
|---|---|
| 单元/契约测试中**显式注入**内存替身、fixture、fake dispatcher | 启动 Orchestrator / Java Data Plane 时因 `development` / 缺配置而 **mock 静默降级** |
| 本地经 SSH 隧道访问云上真实依赖（仍按生产契约） | 「测试环境一套逻辑、生产一套逻辑」的双轨装配 |
| `BDLH_RUNTIME_ENV` 仅作标签/审计字段（若保留） | 用该变量放开 auth、允许空 internal token、允许假 Java/Web 数据冒充成功 |
| 能力 Feature Flag（如 Deep Research）默认关闭且失败可解释 | 用 Flag 掩盖缺 Java / 缺 Registry / 缺凭证仍宣称就绪 |

缺 Java Data Plane、缺 Registry Snapshot、缺 JWT/内部凭证、缺必需 MCP/行情依赖时：**拒绝启动或 `/ready` 失败**，返回可审计错误；不得返回伪装成功的 mock Observation。

### 2.2 与「L0」相关的两类概念（勿混）

| 名称 | 真源 | 含义 | 当前要求 |
|---|---|---|---|
| **ADR-011 的 L0–L4** | ADR-011 / ADR-015 | Memory 与业务真源分层编号（工作记忆 / 会话 / RAG / Mem0 / L4 账本） | **概念保留**；禁止另造第二套层号 |
| **ADR-014 的可恢复 Pause** | ADR-014 | 安全点 **checkpoint** + `pending_*` + Run Registry，Resume 从断点续跑 | **生产契约已批准**；仅 Turn Router + 重放 objective **不算完成** |

实现 ADR-014 时，必须写入真实可恢复位置（`checkpoint_id` 非空且可 resume），禁止用 Mem0 或「重跑用户原话」冒充 L0 恢复。

### 2.3 唯一产品路径

```text
Client / Console
  → FastAPI / SSE
  → Cognitive Orchestrator          # 唯一顶层编排
  → Domain Dispatcher
  → Finance Runtime                 # 当前唯一 Domain
  → Capability Gateway
  → MCP / Java Data Plane / Web / Local deterministic engine

Java Data Plane
  → PostgreSQL（runtime / registry / business / messaging）
  → Transactional Outbox
  → RocketMQ（异步投递，非状态真源）

Memory Service
  → memory schema / Mem0（非 L4 真源）
```

固定边界：

- Cognitive Orchestrator 是唯一顶层产品编排入口。
- Finance Runtime 是金融领域唯一入口。
- Java Data Plane 是结构化业务数据、运行数据和 Registry 的唯一数据库访问边界。
- Orchestrator 不直连业务/runtime/registry PostgreSQL；只通过 Java 内部用例 API 读写。
- Memory Service 是独立 Python 服务；记忆不是业务事实真源。
- RocketMQ 只负责异步投递；PostgreSQL 业务表与 Outbox 才是事务真源。
- 当前 PostgreSQL 与 RocketMQ 都按单实例轻量部署，不建设数据库集群。

## 3. 全量替换原则

1. 修改契约时同时修改生产代码、调用方、测试、SQL 和文档。
2. 删除字段就是物理删除，不保留废弃字段、别名、双写或读取兜底。
3. 删除执行路径就是删除代码和装配，不保留开关切回旧路径。
4. 数据库按空库全量脚本维护（根目录 `db/`）；执行顺序以 `db/execution/` 最新说明为准；**应用启动不执行 DDL/seed/迁移**。
5. 测试替身只能由测试显式注入，不得成为开发或生产启动兜底。
6. 一个数据集、一个契约和一个能力目录都只能有一个真源。

## 4. 核心设计规则

### 4.1 入口与编排

- 快路径只处理闲聊、稳定概念解释和明确禁止请求。
- 未命中快路径时进入理解模型，产出 `goals[]`、实体、约束、缺口和 `needs_external`。
- 理解阶段不得输出业务 Route、Skill ID、`analysis_type` 或固定工具计划。
- Agent 只能从本轮 `allowed` 能力中选择动作。
- `GoalCoverage` 根据 Observation 引用决定完成、继续、询问或受限结束。
- 同 session 有 `pending_*` 时必须经 Turn Router（`resume` / `new_turn` / `ask_which`），禁止盲目 resume。

### 4.2 Registry 与能力菜单

- Capability、Operation、Toolset、Skill 及其关联以 PostgreSQL `registry` schema 为唯一真源。
- Java Data Plane 提供只读 Registry Snapshot API。
- Orchestrator 只加载远程快照并执行纯算法校验，不保留内置业务目录。
- 菜单按 `effective_operations → eligible → allowed` 计算；用户原句和 LLM 不参与授权。
- `allowed` 直接扁平提供给 Agent；不实现 ToolWindow、展开动作或第二套向量筛选。
- Gateway 执行前再次校验身份、权限、只读属性和参数。

### 4.3 数据和分析

- 外部数据统一转换为 Observation，并携带来源、时间、质量和限制。
- 确定性计算与 LLM 表达分离；模型不能伪造行情、账户、持仓或计算结果。
- `StockResearchResult` 是客观研究结果；Suitability 使用权威用户事实（LIVE / USER_CONFIRMED）并在缺数时 fail-closed。
- `analysis_type` 不属于任何当前契约、状态、幂等键、数据库列或路由条件。

### 4.4 持久化、Pause 与消息

- Chat、Run、History、Task、Registry、Outbox 和 Inbox 由 Java Data Plane 管理。
- Task 状态以数据库为准，RocketMQ 消息不是任务状态真源。
- Outbox Relay 只投递已提交事件；消费者使用自己的 Inbox 做幂等。
- Pause / Resume 必须满足 ADR-014：协作停止 + **可恢复 checkpoint** + `pending_*` + Run Registry；仅 abort SSE 不算 Pause。

### 4.5 安全

- 身份来自服务端验证结果，禁止信任请求体中的用户标识。
- 当前金融能力只读；写账户、下单和资金操作必须拒绝。
- 跨用户访问、越权能力调用、提示注入和敏感日志必须有测试。
- 外部内容只能作为不可信数据，不能成为系统指令。

## 5. 相对架构的未完成清单（执行债）

以下条目在统一生产架构 / ADR 中已冻结或批准，**不得**用「短链路够用」「切片 CURRENT」宣布完成。关闭一项必须同时改代码、测试与架构状态表。

| ID | 缺口 | 权威出处 | 完成标准（摘要） |
|---|---|---|---|
| G1 | 真 L0 / Checkpoint 续跑 | ADR-014；架构 §3 / §9 | **CLOSED（2026-08-17）**：Pause/ASK_USER 写入非空 `checkpoint_id` + `cognitive_checkpoint`；Resume 经 L0 快照恢复 goals/行动游标，禁止仅重放 objective |
| G2 | 入口 Goal + Registry 八表 + `eligible→allowed` | 01 号 Prompt；架构实施状态 | **CLOSED（2026-08-17）**：八表 + 菜单装配；LLM Understand（规则降级）→GoalCoverage；业务路径按 `requires_financial_snapshot` 而非 FinancialIntent 分流；Manifest/Descriptor 仅从 Registry Snapshot 投影，无第二份能力清单 |
| G3 | 运行时去环境双轨 | 本文件 §2.1；架构 §17 | **CLOSED（2026-08-17）**：Java/Web Adapter 缺依赖一律 `UNAVAILABLE`；非 `test` 强制 `JAVA_DATA_INTERNAL_TOKEN` 与 Java 可达探测；`from_environment` 默认鉴权开启且无内置 JWT；单测仅 `environment=test` + 显式注入 |
| G4 | Suitability 生产规则集 | ADR-004（批准前 fail-closed） | **CLOSED（2026-08-17）**：`suitability-v0.1`/`DRAFT` 可跑个性化筛查，但不得产出 `SUITABLE`；`APPROVED`+已确认拟投入才可 `SUITABLE`；真实性不足 → `USER_FACTS_CONFIRMATION_REQUIRED` |
| G5 | USER_CONFIRMED / LIVE 用户事实闭环 | 架构 §10；L4 | **CLOSED（2026-08-17）**：Java 确认 API（版本/幂等/审计）+ Console 资料确认；无 v2 confirmation 的 java-api 不得抬升为 LIVE/CONFIRMED；适配缺口引导「打开金融资料确认」 |
| G6 | Deep Research 生产切流 | ADR-016 | **CLOSED（2026-08-17）**：Flag+百炼门禁同时满足才进 allowed；Finance 默认可执行 `research.deep_search`；超预算 → ADR-014 Pause；装配禁止假 `COMPLETE` |
| G7 | Memory remote + Outbox→MQ 闭环 | ADR-011/015/017 | **CLOSED（2026-08-17）**：可切 `BDLH_MEMORY_MODE=remote`；Chat 入口召回/出口 Writer；L4 元数据禁入 Outbox；失败标记 degraded；L0/L1/L4 仍经 Java fail-closed |
| G8 | PORTFOLIO_IMPACT / GOAL_PLANNING | 架构 Domain 意图 | **CLOSED（2026-08-17）**：`portfolio-health` 默认 CURRENT/启用；影响意图走快照+估值证据链；无目标不假 COMPLETE；缺授权 fail-closed |

实施任何 TASK 时，必须在交付报告的「未完成事项」中引用上表 ID，不得省略。

## 6. 实施流程

1. 读取当前代码、测试、根目录 `db/`、统一生产架构 §3 状态表与相关 ADR。
2. 列出本次要删除的旧结构、要关闭的缺口 ID（§5）以及最终唯一结构。
3. 在一个工作范围内同步修改所有生产引用和测试引用。
4. 若数据库结构变化，直接修改全量 schema / seed，并在 `db/execution/` 追加一份当日执行说明；确保服务启动无 DDL。
5. 执行静态检查、单元测试、契约测试和必要的空库脚本静态审查。
6. 搜索已删除术语，生产代码和当前测试中必须为零。
7. 汇报实际完成项、验证结果和仍未关闭的 §5 缺口，不沿用过时阶段口号。

## 7. 验证基线

至少执行：

```text
bdlh-runtime-orchestrator: uv run ruff check . && uv run pytest -q
bdlh-runtime-data:         mvn -q test
bdlh-memory-service:       uv run pytest -q
```

涉及前端、部署或 SQL 时，再执行对应测试或静态校验。未经用户要求，不连接真实数据库、不启动真实 RocketMQ、不提交、不推送。

## 8. 完成定义

- 默认运行路径只有 Cognitive → Domain Dispatcher → Finance。
- 运行时行为满足 §2.1（无开发宽松降级）。
- `analysis_type` 在生产源码、测试 fixture、当前 SQL 和当前 Prompt 中不存在。
- Registry 只有数据库一份目录，Orchestrator 不含业务目录兜底。
- `eligible → allowed → Gateway` 权限链可测试且不受用户原句影响。
- 所有结构化数据库访问经过 Java Data Plane；Memory 只访问自己的 schema。
- 根目录 `db/` 能从空库创建完整结构；服务启动没有 DDL、种子或自动迁移执行。
- ADR-014：存在真实可恢复 checkpoint（§5 G1 关闭），Turn Router 常绿。
- 旧 Root Graph、旧字段投影、双写、影子读取和「仅测试环境可启动」的产品分支不存在。
- 全部相关测试通过；架构 §3 状态表与 §5 缺口表一致。

## 9. 明确禁止

- 为「先上短链路」保留假 checkpoint、假 LIVE 或假 COMPLETE。
- 为开发阶段保留旧字段、旧 API 投影或 environment 双轨产品逻辑。
- 新旧对象双写、旧表回填、影子读取和按版本分流。
- 在 Orchestrator 或 Memory Service 中直连并修改 Java 所有的 schema。
- 应用启动时执行 DDL、种子或自动迁移（含未接线的 Flyway）。
- 在 Python、Java 和 SQL 中各维护一份 Capability/Skill 清单。
- 恢复旧 Root Graph、第二套 Finance 编排或自动回退旧路径。
- 用 Mock、空目录或内存默认值掩盖配置错误。
- 把历史阶段报告或「切片 CURRENT」作为已完成生产契约的证明。

## 10. 交付格式

```text
# 结果

## 完成内容
## 删除内容
## 关闭的缺口（§5 ID）
## 唯一真源检查
## 数据库启动边界
## 生产唯一运行标准检查（§2.1）
## 验证结果
## 未完成事项（引用 §5 ID）
```
