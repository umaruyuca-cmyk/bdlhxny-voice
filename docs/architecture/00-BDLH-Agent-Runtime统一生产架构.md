# BDLH Agent Runtime 统一生产架构

> **文档状态：生产架构唯一权威基线**  
> **架构版本：v1.6**  
> **生效日期：2026-08-11**  
> **适用范围：`bdlh-runtime-orchestrator`、Java 用户数据服务、前端/API Gateway、外部数据服务及生产基础设施**  
> **当前实施状态：目标架构已冻结；M1 已完成独立开发，M0 门禁未关闭，尚未进入生产路径切换**  
> **配套架构图：[00-BDLH-Agent-Runtime生产架构.drawio](./00-BDLH-Agent-Runtime生产架构.drawio)**

## 产品身份（定位声明，不编号）

BDLH Agent Runtime 的产品身份是**通用 Agent Runtime / 编排内核**：认知编排、领域调度、统一能力网关、观察标准化、四时点治理、确定性计算隔离和生产持久化都属于与业务领域无关的内核。

**金融是挂载在该内核上的第一个 Domain（业务领域）；股票客观研究、组合健康和 Suitability 等才是该领域内的 Skill，不是内核本身。** 后续可以挂载更多 Skill 或更多 Domain；多 Agent 是可选演进方向，不是当前身份。

因此阅读本文时必须区分两类内容：

| 类别 | 判定方法 | 变更影响 |
|---|---|---|
| 内核（Runtime） | 描述不含任何金融词汇也能成立 | 影响所有现有与未来 Skill，变更门槛最高 |
| 域（Domain / Skill） | 描述依赖金融语义、金融契约或金融数据源 | 只影响该 Domain，可独立演进 |

定位相关的增量决策见 [ADR-009](./ADR-009-Runtime-Domain-Skill定位与命名.md)；升级依据与未执行条目见 [04-Runtime定位升级修改意见](../reviews/04-Runtime定位升级修改意见.md)。本声明只改变叙事与扩展面，不改变 §18 的 M0–M6 迁移主线、门禁和退出条件。

## 0. 文档治理

### 0.1 本文档的权威性

本文是 BDLH Agent Runtime 面向开发、测试、部署和运维的统一生产架构文档。

发生架构、代码和历史文档冲突时，按以下优先级处理：

1. 安全、隐私、身份和只读金融边界；
2. 本文档；
3. 已批准的 ADR 或接口契约；
4. 当前代码与测试所证明的实现事实；
5. 生产开发实施 Prompt；
6. 已归档历史设计文档、评审记录和 Git 历史。

已归档历史设计文档中的有效经验已吸收到本文、ADR 或生产开发实施 Prompt，不再作为当前
开发依据：

- V3 历史档案保留 LangGraph、MCP、Observation、预算和确定性计算经验；
- 本文保留 Cognitive Kernel 的生产目标模型；
- 本文保留 Finance Runtime、Stock Research 和 Suitability 的生产领域模型；
- 本文统一处理三者之间的生产边界、部署方式和迁移顺序。

### 0.2 文档中的状态标记

| 标记 | 含义 |
|---|---|
| `CURRENT` | 当前代码已进入默认运行路径并有测试覆盖 |
| `FOUNDATION` | 契约或骨架已存在，但尚未进入默认运行路径 |
| `TARGET` | 已冻结的生产目标，需要按迁移计划实现 |
| `EXPERIMENTAL` | 不得进入生产关键路径 |
| `RETIRED` | 不得新增依赖，按计划退出 |
| `TRANSITION` | 已进入运行路径但处于迁移过渡期（如新路径已装配未接默认流量） |
| `DEVELOPMENT_COMPLETE` | 实现已完成但被生产门禁阻塞，未进入默认运行路径 |
| `RELEASE_BLOCKED` | 实现完成但因 §19.2 release-blocking 条件未满足而无法发布 |

对于 Capability Registry、Domain Dispatcher、SkillManifest、Observation Normalizer 等
基础设施级组件，`CURRENT` 表示已完成应用装配、启动校验并有测试覆盖；它不等于已经进入
默认用户流量。默认切流仍由 `TRANSITION`、`DEVELOPMENT_COMPLETE`、`RELEASE_BLOCKED`
和 M5 灰度门禁共同判断。

任何设计说明都必须明确其状态，禁止把目标架构描述成已经落地。

### 0.3 版本记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-08-10 | 统一生产架构首个权威基线 |
| v1.1 | 2026-08-11 | 定位升级（ADR-009 ~ ADR-012）：产品身份声明、§1 主线标注内核/域、§2 拆分内核范围与首个 Domain、§5.4 引用 `SkillManifest`、§9.1 引用 Memory 分层 |
| v1.2 | 2026-08-11 | 文档面收口（ADR-013）：§0.3 新增版本记录；§3/§7 登记 Domain Dispatcher、manifest 契约与内核纯净度门禁；§18 M1 改名并追加可选 M7；§19.1 登记架构边界测试；§22 补录 README 与图纸处置；§23 拆出「已起草未批准」并登记 ADR-004；配套架构图标签对齐 |
| v1.3 | 2026-08-11 | §22 登记新增的 `docs/00-BDLH-Agent-Runtime仓库文件管理树.md`（文件归属索引，非决策来源） |
| v1.4 | 2026-08-11 | 文档与代码现状对齐 + 通用化沉淀：§0.2 补登记 `TRANSITION`/`DEVELOPMENT_COMPLETE`/`RELEASE_BLOCKED`；§3 更新 Dispatcher（已带 descriptor）、SkillManifest（已落地 ADR-010 §6.1）、PortfolioValuationBuilder（M3 完成）、Toolset/能力计数；§4 拓扑图插入 Domain Dispatcher 节点并与 §1 主线对齐；§4.2 内核行去金融词；§10.1 补 Toolset 命名规则、§10.2 标注为 finance 实例；§13.2/§15.3 拆分为通用内核规则 + finance 域实例标注 |
| v1.5 | 2026-08-11 | 修正实施状态残留：统一 ADR-010 已落地、PortfolioValuationBuilder 已完成但尚未发布的表述；同步 M3、§20、§23.1 与 01 号说明的术语和 Skill 状态 |
| v1.6 | 2026-08-11 | 收口文档治理与状态语义：更新 §0.1 的历史文档称呼；补充基础设施级 `CURRENT` 不等于默认切流的说明；§19.1 登记 manifest/descriptor 启动校验测试 |

版本号只反映本文的表述与登记变化；阶段范围、契约字段语义与发布门禁的任何调整必须另有 ADR。

## 1. 执行摘要

BDLH Agent Runtime 的生产架构采用以下唯一主线：

```text
Nginx / API Gateway                                  [内核]
  → Python FastAPI                                   [内核]
  → LangGraph Cognitive Orchestrator                 [内核]
  → Domain Dispatcher（DomainRegistry）              [内核]
  → Domain Runtime = Skill 宿主                      [域，当前唯一实例：Finance Runtime]
  → Skill                                            [域，当前：Financial Skill]
  → Toolset / Capability Gateway                     [内核]
  → MCP / Java Data API / Web Search / Local Domain Engine
  → Observation / Evidence                           [内核]
  → StockResearchResult / SuitabilityAssessment      [域输出契约]
  → Communication Plan / Response Verification       [内核]
  → SSE / JSON                                       [内核]
```

四时点 Guardrails（§11）是贯穿上述主线的横切治理，不是链上的某一层；任何新增 Skill 自动继承，不得自带私有 Guardrail。

生产决策如下：

1. **生产只使用 LangGraph Runtime**。Letta 仅允许在隔离实验环境中对比，不属于生产架构。
2. **Cognitive Kernel 是目标顶层编排器**，但它只选择行动，不直接访问原始工具。
3. **Finance Runtime 是金融领域边界**，负责金融任务、Skill、Toolset、证据和适配性。它同时是 Domain Dispatcher 之下的一个 Skill 宿主实例，只做校验、选 Skill、授权求交、调 Capability 和组装 Outcome。
4. **Stock Research 是金融 Skill，不是顶层系统**。
5. **Capability Registry 是唯一能力真源**；Toolset 只是派生视图，不能复制第二份能力清单。
6. **所有外部数据先转为 Observation**，任何模型不得直接消费原始供应商响应并生成最终结论。
7. **金融计算由确定性 Domain Engine 完成**，LLM 不执行指标、风险、估值或回测公式。
8. **客观研究与用户适配性分离**。`StockResearchResult` 不包含“适合当前用户”的结论。
9. **系统对外保持只读**。不下单、不调仓、不转账、不修改账户或持仓。
10. **生产环境禁止 mock 数据静默降级**。不可用必须返回 `PARTIAL / LIMITED / FAILED`。
11. **状态、会话、运行索引、历史和任务必须持久化**，生产实例不得依赖进程内存保存关键状态。
12. **新旧路径渐进切换**。新路径未通过安全、故障注入和灰度门禁前，旧路径继续保留。
13. **内核与领域分离**。Cognitive Orchestrator 与 Domain Dispatcher 是领域无关内核，不得依赖任何具体领域的枚举、契约或计算模块；领域语义（如 `FinancialIntent`）只存在于对应 Domain 的私有契约中。新增 Skill 或 Domain 只允许注册，不允许复制 Capability Registry、Observation、Guardrail、预算或审计链。

## 2. 业务范围

本节按「内核范围」和「域范围」分别声明。域范围变化不需要改内核范围表；内核范围变化必须评估对全部已挂载 Skill 的影响。

### 2.1 内核能力范围（Runtime，与领域无关）

第一阶段内核提供以下与业务领域无关的能力：

- 认证身份绑定与用户隔离；
- `InputEvent` 归一化（用户消息、恢复、定时唤醒）；
- 认知编排与 `CognitiveAction` 选择；
- Domain 调度：按 `DomainRequest` 路由到已注册 Domain Runtime，并拒绝未注册域或未启用能力；
- Capability Registry 作为唯一能力真源，Toolset 为派生视图；
- 外部数据统一转为 Observation，携带来源、时间、质量和降级信息；
- 四时点 Guardrails；
- 预算、超时、重试、熔断与降级语义；
- Communication Plan 与 Response Verification；
- 多轮会话、流式输出、运行查询与中断恢复；
- 状态、会话、运行索引、历史、审计与任务的持久化；
- 结构化日志、指标与 SLO。

以上能力不因更换或新增 Domain 而重写，这也是本系统可迁移到非金融场景的部分。

### 2.2 首个 Domain：金融（只读）

#### 2.2.1 当前生产范围

第一阶段生产系统提供只读金融助手能力：

- 稳定金融知识解释；
- 股票、ETF、基金和指数标的解析；
- 实时行情和历史行情查询；
- 技术面、基本面、估值、行业、资金流和新闻研究；
- 用户持仓、账户、交易历史和风险画像的只读分析；
- 股票客观研究；
- 组合影响分析；
- 用户适配性评估；
- 多轮会话、流式输出、运行查询和中断恢复；
- 数据缺失、冲突和限制披露。

#### 2.2.2 第二阶段范围

- 价格或估值观察任务；
- 组合风险扫描；
- Scheduler 唤醒；
- 受控主动通知；
- 周期性财务复盘；
- 财务目标和现金流能力扩展。

#### 2.2.3 后续 Skill / Domain 的挂载方式

新增能力只允许通过以下方式扩展，且不改变本节金融范围：

| 扩展物 | 挂载位置 | 允许新增 | 禁止 |
|---|---|---|---|
| 同域新 Skill | `finance` Domain Runtime 内 | Skill 声明与业务实现 | 新建第二份 Capability Registry |
| 新 Domain | 注册到 Domain Dispatcher | Domain 声明、Skill、自有确定性引擎 | 自建 Adapter 层、Observation 或审计链 |
| 检索增强（RAG，见 [ADR-013](./ADR-013-RAG作为可插拔KnowledgeSkill的边界.md)） | 某 Domain 下的检索类 Skill | 检索结果转 Observation 后作为 Evidence 候选 | 作为内核中心；Cognitive 直接检索；检索文本免除 §10.4 不可信输入处理 |
| 多角色 / 多 Agent | Cognitive 内部角色子图 | 角色声明与预算切分 | 新增部署单元、第二套 Tool 层、角色直连 Capability |

Skill 与 Domain 的自描述契约见 [ADR-010](./ADR-010-SkillManifest与DomainDispatcher契约.md)；多 Skill 与多 Agent 的演进阶梯、准入条件与禁止复制清单见 [ADR-012](./ADR-012-多Skill与多Agent演进门槛.md)。当前所处位置是「单 Domain 多 Skill」，多角色与多 Agent 不在第一、第二阶段范围内。

### 2.3 明确非目标

- 真实下单、撤单、改单、调仓或资金划转；
- 券商交易执行；
- 自动生成可直接提交的订单；
- 自动承诺收益；
- 冒充持牌投资顾问；
- LLM 直接访问数据库、MCP 原始工具或账户服务；
- 在运行时从磁盘、网络或用户输入动态加载未经审查的 Skill（一等 Skill 必须编译期注册，并在启动时对 Capability Registry 校验；此处禁止的是热加载与未审查来源，不是禁止扩展 Skill）；
- 在生产关键路径中运行 Letta；
- 用 Node `stock-analysis-skill` 承担生产编排或在线补数；
- 以 Mem0 替代用户档案、金融账本、任务库或审计历史。

## 3. 当前实现与目标架构

| 能力 | 状态 | 当前事实 | 生产目标 |
|---|---|---|---|
| FastAPI / SSE / Agent Run API | `CURRENT` | 已有 `/api/v1` 路由 | 保持兼容并统一错误与事件契约 |
| JWT 身份绑定 | `CURRENT` | Python 验签，Java 提供用户数据 | 生产强制开启，禁止信任请求体 `user_id` |
| 旧 Root Graph | `CURRENT` | 默认执行路径 | 迁移期保留，最终由 Cognitive Graph 替代 |
| CognitiveAction | `FOUNDATION` | 九种行动契约已存在 | 第一阶段启用 RESPOND、ASK_USER、INVOKE_DOMAIN |
| Cognitive Graph | `TARGET` | 尚未进入运行路径 | 成为唯一顶层业务编排入口 |
| DomainRequest / Outcome | `FOUNDATION` | 严格契约已存在 | 作为 Cognitive 与 Finance 的唯一跨层接口 |
| Domain Dispatcher | `CURRENT` | `DomainRegistry` 已提供 domain→runtime 唯一映射、拒绝重复注册，并携带 `DomainDescriptor` 支持 intent 启用查询 | 继续作为路由与拒绝的唯一入口；新增 Domain 只需注册 |
| SkillManifest / DomainDescriptor | `CURRENT` | 已落地（ADR-010 §6.1）：通用模型 `domains/manifests.py` + finance 一份 descriptor + 三份 manifest 声明现状；启动时对 Capability Registry 逐项校验，不一致则 fail-fast | 继续作为 Skill 自描述的唯一契约真源 |
| 内核纯净度门禁 | `CURRENT` | `tests/architecture/test_kernel_purity.py` 静态断言内核不依赖领域实现 | 保持常绿，随内核目录变化同步更新 |
| Finance Runtime | `TRANSITION` | M1 薄运行时已独立装配，未接默认流量且无 Checkpointer | 领域子图/应用服务，隔离金融业务逻辑 |
| StockResearchResult | `DEVELOPMENT_COMPLETE` / `RELEASE_BLOCKED` | M2 Builder 已在非默认 Finance Runtime 接线并完成回归；尚未因发布门禁进入默认流量 | 客观股票研究唯一输出契约 |
| Financial User Facts v2 | `FOUNDATION` | Java 已提供鉴权确认入口、版本与幂等控制、审计记录及只读查询元数据；Python 已按事实来源归一化 | 作为账户、持仓与风险事实的唯一权威来源，禁止旧记录被推断为实时数据 |
| PortfolioValuationBuilder | `DEVELOPMENT_COMPLETE` / `RELEASE_BLOCKED` | M3 切片已完成：以 `quantity × price` 重算市值/权重，sha256 内容寻址，fail-closed 校验；能力 `portfolio.build_current_valuation` 已注册；尚未因发布门禁进入默认流量 | 使用权威持仓和受预算约束的市场报价生成可追溯估值快照 |
| SuitabilityEngine | `TARGET` | Schema 已存在，规则未实现 | 确定性个性化适配评估 |
| Capability Registry | `CURRENT` | 15 个统一只读能力（含 M3 `portfolio.build_current_valuation` 确定性重算） | 继续作为唯一能力真源 |
| Toolset Registry | `TRANSITION` | 六个 finance 域派生分组已存在并接入 M1 Finance Planner；PORTFOLIO_READ 含估值重算能力 | 继续分层暴露能力并服务后续 Research/Suitability |
| 四时点 Guardrails | `FOUNDATION` | 只有契约和 Protocol | 切换前必须全部实现并接线 |
| Observation / Coverage | `CURRENT` | 已有标准化与覆盖判断 | 进入所有外部数据路径 |
| Mem0 | `CURRENT` | 可用时增强、失败降级 NoOp | 保持非关键路径，不存权威业务事实 |
| Checkpointer | `CURRENT` | 生产可使用 PostgreSQL | 必须持久化并隔离命名空间 |
| Chat Session | `CURRENT` | 生产已有 PostgreSQL Store | 继续持久化和用户隔离 |
| Run Registry | `FOUNDATION` | 当前只有内存实现 | 上线前迁移 PostgreSQL |
| Analysis History | `FOUNDATION` | 当前只有内存实现 | 上线前迁移 PostgreSQL并保证幂等 |
| Task / Scheduler | `TARGET` | 尚未实现 | 第二阶段只落地一个观察任务垂直切片 |
| Letta | `EXPERIMENTAL` | 无生产实现 | 仅隔离研究，不进入部署拓扑 |
| Node Stock Skill / Wrapper | `RETIRED` | 遗留 Java 链路仍可能使用 | Python 新路径禁止依赖，逐步退出 |

## 4. 系统上下文与生产拓扑

```mermaid
flowchart TB
    USER["Web / App 用户"] --> EDGE["Nginx / TLS / Rate Limit"]
    EDGE --> FE["Frontend 静态站点"]
    EDGE --> PYAPI["Python FastAPI :8090"]
    EDGE --> JAVA["Java Backend :8081"]

    PYAPI --> COG["LangGraph Cognitive Orchestrator（内核）"]
    COG --> DISP["Domain Dispatcher（内核）"]
    DISP --> FIN["Finance Runtime（域·当前唯一实例）"]
    FIN --> CAP["Capability Gateway（内核）"]

    CAP --> MCP1["cn-financial MCP"]
    CAP --> MCP2["akshare-one MCP"]
    CAP --> SEARCH["Web Search Wrapper"]
    CAP --> JAVA
    CAP --> ENGINE["Deterministic Domain Engine"]

    PYAPI --> PG[("PostgreSQL")]
    PYAPI --> REDIS[("Redis 可选缓存/限流")]
    PYAPI --> MEM["Mem0 可选语义记忆"]
    PYAPI --> LLM["DeepSeek / Approved LLM"]

    SCHED["Scheduler / Wake-up Worker"] --> PYAPI
```

> **拓扑说明：** Domain Dispatcher 为内核组件（§1 主线、ADR-009），当前路由到唯一实例 Finance Runtime。新增 Domain 只需向 Dispatcher 注册 descriptor，不新增内核节点、不新增第二套 Capability Gateway 或 Observation 链。节点标签中的 `[内核]`/`[域]` 划分对齐 §1 主线；具体供应商名（cn-financial MCP / akshare-one MCP / DeepSeek）为 finance 域当前实例，非内核规范。

### 4.1 公网边界

公网只暴露 Nginx 的 HTTPS 入口。Python、Java、Web Search、数据库和 Redis 不直接监听公网地址。

推荐路由归属：

| 路径 | 归属 |
|---|---|
| `/`、`/workspace`、`/agent` | Frontend |
| `/api/v1/chat/*` | Python Analysis |
| `/api/v1/conversations*` | Python Analysis |
| `/api/v1/agent-runs*` | Python Analysis |
| `/api/auth/*` | Java Backend |
| `/api/portfolio/*` | Java Backend，公网访问受 JWT 约束 |
| `/api/user/*` | Java Backend，公网访问受 JWT 约束 |
| `/actuator/*` | 仅运维网络或关闭公网访问 |

Python 调用 Java Data API 使用内网地址和服务凭证，不经过公网 Nginx。

### 4.2 生产单元

| 单元 | 是否关键 | 说明 |
|---|---|---|
| Nginx | 是 | TLS、路由、SSE、限流、请求大小和超时 |
| Python Analysis | 是 | 通用编排内核：认知编排 + 域调度 + 能力网关 + 治理；当前挂载 finance 域 |
| Java Backend | 个性化场景是 | 认证、用户；finance 域业务数据（持仓、账户、风险画像）的权威存储 |
| PostgreSQL | 是 | Checkpoint、会话、运行索引、历史、任务和审计 |
| Redis | 否 | 缓存、分布式限流或短期锁；不能作为唯一真相源 |
| MCP 服务 | 数据场景是 | 外部数据供应商（当前实例：金融行情 MCP），允许能力级降级 |
| Web Search | 否 | 公开资料补充，失败不阻断主路径 |
| LLM | 模型场景是 | 理解、规划和表达；确定性计算不依赖它 |
| Mem0 | 否 | 语义记忆增强，失败时无记忆继续 |
| Scheduler | 第二阶段是 | 只唤醒任务，不生成域结论 |

## 5. 逻辑分层

### 5.1 API 与身份层

职责：

- JWT 验证；
- 从 Token subject 构造可信 `authenticated_user_id`；
- 请求 Schema 校验；
- `run_id / thread_id / session_id` 创建与绑定；
- SSE/JSON 序列化；
- 对外错误码映射；
- 用户级限流和请求大小限制。

禁止：

- 直接拼装 Graph 内部任意 State；
- 使用请求体 `user_id` 作为生产身份；
- 将 Token 写入 State、Checkpoint、事件或日志。

### 5.2 Cognitive Orchestrator

职责：

- 将用户消息、恢复、定时唤醒等统一为 `InputEvent`；
- 构建最小 `CognitiveState`；
- 识别目标、约束和不确定性；
- 选择 `CognitiveAction`；
- 调用 `DomainRequest`；
- 吸收 `DomainOutcome`；
- 构建 Communication Plan；
- 决定回答、追问或受控任务动作。

第一阶段只启用：

```text
RESPOND
ASK_USER
INVOKE_DOMAIN
```

`CREATE_TASK / UPDATE_TASK / WAIT / NOTIFY / DO_NOTHING / RETRIEVE_MEMORY` 可以存在于契约，但未启用时必须返回 `ACTION_NOT_ENABLED`，不能假装已经执行。

### 5.3 Finance Runtime

职责：

- 验证 `FinancialDomainRequest`；
- 加载本轮最小 Financial Snapshot；
- 选择 Financial Skill；
- 建立 Skill 依赖计划；
- 选择 Toolset，并展开受控 Capability；
- 执行 Capability 并收集 Observation；
- 构建 Evidence、Finding 和 Conflict；
- 调用确定性 Domain Engine；
- 生成 `StockResearchResult`；
- 按需要执行 Suitability；
- 生成 `FinancialDomainOutcome`。

Finance Runtime 不直接生成最终聊天文案。

### 5.4 Financial Skill

生产第一阶段只实现并开放：

1. `stock-research`；
2. `portfolio-health`；
3. `suitability-evaluation`。

Skill 是 Python 运行时中的明确业务模块或子图，是编译期注册的一等对象，不是运行时动态加载的 Prompt 文件，也不是 Node Wrapper。

每个 Skill 必须声明以下内容，字段表以 [ADR-010](./ADR-010-SkillManifest与DomainDispatcher契约.md) 的 `SkillManifest` 为唯一真源，本节不再重复维护第二份清单：

- 身份：`skill_id`、`skill_version`、`domain`、`status`；
- 输入契约与可处理意图、输入约束；
- 输出契约与 `authority_field`（权威载荷字段）；
- 权限要求：精确 `DomainOperation`，禁止前缀授权；
- 所需 Toolset 与精确 Capability 名；
- 数据完成条件（含允许的 `data_mode`）；
- 预算（复用 `DomainBudget`，不新增第二套预算模型）；
- 降级规则；
- 幂等行为与副作用声明（第一阶段必须为空，即只读）。

`SkillManifest` 声明的 Capability、Toolset 与 `DomainOperation` 名必须在启动时逐项对 Capability Registry 校验，不一致时启动失败；Capability Registry 仍是「有哪些能力」的唯一真源。Domain 一侧的自描述（`DomainDescriptor`）与 Dispatcher 的拒绝行为同见 ADR-010。

### 5.5 Capability 与 Adapter

Capability 是 Agent/Planner 可理解的稳定业务能力，例如：

- `market.get_realtime_quote`；
- `market.get_historical_prices`；
- `portfolio.get_current_positions`；
- `research.web_search`；
- `analysis.run_analysis`。

Adapter 负责把 Capability 翻译为供应商或服务具体调用。上层不得看到 MCP 原始工具名、URL、传输协议和供应商参数。

### 5.6 Deterministic Domain Engine

负责：

- 指标；
- 风险；
- 估值；
- 回测；
- 组合暴露；
- Suitability 规则；
- 覆盖率、可信度和阈值判断。

依赖规则：

```text
Domain Engine 不 import LangGraph / LangChain / MCP / Mem0 / FastAPI
```

固定输入必须得到固定输出；涉及日期时必须显式注入交易日历和 `as_of`。

## 6. 核心运行流程

### 6.1 稳定知识直接回答

```mermaid
sequenceDiagram
    participant U as User
    participant A as API/Auth
    participant C as Cognitive
    participant G as Response Guardrail
    participant L as LLM
    U->>A: message + JWT
    A->>C: InputEvent(authenticated_user_id)
    C->>C: 选择 RESPOND
    C->>L: 仅稳定知识上下文
    L-->>C: Draft Response
    C->>G: 事实与风险表达复核
    G-->>A: Verified Response
    A-->>U: SSE / JSON
```

直接回答禁止处理实时价格、账户事实或依赖外部证据的结论。

### 6.2 股票客观研究

```mermaid
sequenceDiagram
    participant C as Cognitive
    participant F as Finance Runtime
    participant P as Finance Planner
    participant K as Capability Gateway
    participant D as Data Providers
    participant E as Domain Engine
    C->>F: FinancialDomainRequest(STOCK_RESEARCH)
    F->>P: 选择 stock-research + Toolsets
    P->>K: CapabilityPlan
    K->>D: MCP / Web / Local calls
    D-->>K: Raw responses
    K-->>F: Observations + Provenance
    F->>E: Normalized analysis input
    E-->>F: Deterministic results
    F-->>C: FinancialDomainOutcome + StockResearchResult
```

### 6.3 用户适配性分析

```text
StockResearchResult
  + FinancialSnapshot(LIVE / USER_CONFIRMED)
  + 用户目标和约束
  → SuitabilityEngine
  → SuitabilityAssessment
```

硬性规则：

- `MOCK / UNAVAILABLE` 快照不得产生真实个性化结论；
- 研究覆盖为 `LIMITED` 时不得输出 `SUITABLE`；
- 缺少风险画像、持仓或流动性关键字段时返回 `INSUFFICIENT_INFORMATION`；
- Suitability 输出理由、Rule ID、证据、条件和限制；
- Suitability 只做评估，不生成交易指令。

### 6.4 持续任务唤醒

第二阶段流程：

```text
Scheduler
  → SCHEDULED_WAKEUP InputEvent
  → Cognitive Kernel
  → Finance Runtime 重新取最新数据
  → 判断触发条件
  → NOTIFY 或 WAIT / DO_NOTHING
```

Scheduler 不缓存上次结论，不自行调用 LLM，不自行生成通知内容。

## 7. 代码组织与依赖规则

目标逻辑与当前目录映射：

| 逻辑层 | 当前/目标目录 | 规则 |
|---|---|---|
| API/Auth | `api/` | 只处理 HTTP、身份和序列化 |
| Application Wiring | `runtime/` | 配置、装配、持久化工厂、错误 |
| Cognitive | `cognitive/` + LangGraph graph | 不引用原始 Adapter；不依赖任何具体领域符号 |
| Domain Dispatcher | `domains/registry.py` | 领域无关内核；只按 domain 路由与拒绝，不含业务策略 |
| Finance Runtime | `domains/finance/` | 只通过 Capability Gateway 访问外部能力 |
| Cross-domain Contracts | `domains/contracts.py` | 严格 Pydantic，禁止任意 dict；不得引入领域枚举 |
| Capability/Toolset | `tools/` | Registry 是唯一能力真源 |
| Integration Adapters | `integrations/` 和 Adapter 实现 | 隔离供应商协议 |
| Observation | `observations/`、`contracts/observation.py` | 统一来源、质量、时间和错误 |
| Deterministic Engine | `domain/` | 纯计算，不依赖 Agent 框架 |
| Memory | `memory/` | 可选增强，不是事实源 |
| Persistence | `runtime/*store`，后续收敛到 `persistence/` | 生产必须持久化 |

禁止依赖：

- `domain/` → LangGraph、LLM、MCP、Mem0、FastAPI；
- `cognitive/` → MCP Client、Java HTTP Client、供应商 Tool；
- `domains/finance/` → 供应商原始 Schema；
- Graph Node → 环境变量；
- API → 供应商 Adapter；
- Model 输出 → 直接执行未经 Policy 校验的动作。

为降低迁移风险，本阶段不强制重命名现有 `domain/` 与 `domains/`；新代码必须遵守上述逻辑边界，待运行路径稳定后再单独执行目录重构。

## 8. 稳定契约

### 8.1 标识符

| 标识 | 语义 | 生命周期 |
|---|---|---|
| `user_id` | 服务端认证用户 | 用户级 |
| `session_id` | 前端会话目录 | 多轮会话 |
| `thread_id` | LangGraph Checkpoint 线程 | 多轮状态 |
| `run_id` | 单次 API/Graph 执行 | 单次运行 |
| `request_id` | 单次领域调用 | Domain Request |
| `task_id` | 持续任务 | 第二阶段 |
| `observation_id` | 一次标准化观察 | 单次数据调用 |
| `capability_execution_id` | 能力执行审计与幂等 | 单次能力调用 |

`run_id` 与 `thread_id` 不得混用。生产 Run Registry 必须持久化两者映射。

### 8.2 跨层对象

唯一允许的主要跨层对象：

```text
InputEvent
CognitiveAction
DomainRequest / DomainOutcome
FinancialDomainRequest / FinancialDomainOutcome
FinancialSnapshot
Observation
StockResearchResult
SuitabilityAssessment
CommunicationPlan
PublicResponse
```

规则：

- 跨层对象使用严格 Schema，`extra=forbid`；
- Graph State 中如保存 dict，必须由已验证模型 `model_dump()` 产生；
- 不跨层传递原始 HTTP/MCP 响应；
- 不跨层传递隐藏思维链；
- 所有结论引用 Evidence ID 或 Calculation ID；
- 所有时间使用带时区 ISO-8601；
- 金额、比例和数量在正式计算契约中使用 Decimal 或明确舍入策略。

### 8.3 状态枚举

领域结果：

```text
COMPLETE / PARTIAL / LIMITED / FAILED / WAITING_USER
```

Observation：

```text
SUCCESS / PARTIAL / UNAVAILABLE / FAILED
```

数据真实性：

```text
LIVE / USER_CONFIRMED / TEST_FIXTURE / MOCK / UNAVAILABLE
```

生产逻辑禁止把 `MOCK`、`TEST_FIXTURE` 或 `UNAVAILABLE` 提升为 `LIVE`。

## 9. State、Memory 与持久化

### 9.1 数据所有权

| 数据 | 权威存储 | 是否进入 Graph State |
|---|---|---|
| 用户身份、账户、持仓 | Java/业务数据库 | 仅最小只读快照或引用 |
| Cognitive State | LangGraph PostgreSQL Checkpointer | 是，最小化 |
| Finance Run State | 独立 Checkpoint namespace 或同步子图 | 是，不复制完整账本 |
| Chat Session / Messages | PostgreSQL | State 仅保存必要上下文 |
| Run Registry | PostgreSQL | State 保存 `run_id` |
| Analysis / Decision History | PostgreSQL | State 保存引用 |
| Capability Execution Audit | PostgreSQL | State 保存摘要或引用 |
| Semantic Memory（L3） | Mem0 / 向量存储 | 只保存召回结果摘要 |
| Financial Task | PostgreSQL | State 保存 `task_id` |
| Cache / Rate Limit | Redis | 不作为业务真相源 |

Memory 的分层模型（L0 工作记忆 / L1 会话记录 / L2 检索知识 / L3 长期语义 / L4 业务真源）与「记忆不得自行晋升为业务真源」的边界见 [ADR-011](./ADR-011-Memory分层与晋升边界.md)。其中 L4 不属于记忆体系：账户、持仓、风险画像与审计历史永远从权威业务存储读取，记忆层的同名字段只是派生或提示。`MEMORY_CONFIRMED` 必须携带服务端 `confirmation_ref`，否则等同 `INFERRED`，不得驱动高影响规则。

### 9.2 Checkpoint 隔离

- Checkpoint key 至少包含 `user_id + thread_id + namespace`；
- Cognitive 与 Finance 子图不得共享同一无区分 State；
- 多轮运行必须记录本轮 Observation 起始位置；
- 恢复时校验 `run_id`、`thread_id` 和认证用户一致；
- Checkpoint 不保存 Token、密钥或完整原始账户数据；
- 大型行情数据持久化到独立存储或摘要后再引用，避免 Checkpoint 膨胀。

### 9.3 生产持久化要求

以下任一项仍为进程内存实现时，不允许多副本生产发布：

- Run Registry；
- Analysis History；
- Chat Session；
- Checkpointer；
- Task Store；
- 幂等记录。

## 10. Capability、Toolset 与供应商

### 10.1 唯一能力真源

`CapabilityRegistry` 是唯一真源，记录：

- 稳定名称；
- 描述；
- 领域；
- Adapter 类型；
- 输入 Schema；
- 输出 Schema；
- 是否只读；
- 超时；
- 成本；
- 支持的 Skill 适用范围（字段名仍为 `analysis_types`，语义按 ADR-009 §3.2 理解为 skill scope；改名列为后续可选项，本版不触发回改）；
- 所属 Toolset。

Toolset 由 Capability Registry 动态派生，不维护第二套清单。Toolset 名遵循 `{domain}_{scope}_{read|compute}` 命名模式（ADR-009 §3.2）；新增 Domain 的 Toolset 必须以其 domain 前缀命名，避免跨域同名。

### 10.2 finance 域 Toolset 实例（首个 Domain）

> 以下六个名为 finance 域当前实例，冻结不回改（ADR-009 §3.2）。它们是内核 Toolset 派生规则的 finance 投影，不是通用规范。

```text
market_read
fundamental_read
news_read
portfolio_read
financial_profile_read
planning_compute
```

模型先看到 Toolset，再只看到被选 Toolset 内、满足当前 Skill 适用范围和权限的 Capability。

### 10.3 供应商路由

- MCP Adapter 隐藏 cn-financial 和 akshare-one 的传输差异；
- Java Adapter 隐藏用户数据 HTTP 路径；
- Web Search Adapter 隐藏搜索供应商和凭证；
- Local Adapter 调用确定性 Domain Engine；
- 路由策略由确定性代码管理，模型不能选择供应商地址或原始 Tool。

### 10.4 外部内容安全

新闻、网页、公告和供应商文本均是不可信输入：

- 不得覆盖系统指令；
- 不得改变工具白名单；
- 不得触发新的 Capability；
- HTML/Markdown 必须清洗；
- 引用时保留来源；
- 超长内容先截断和结构化，不直接注入全部上下文。

## 11. 四时点 Guardrails

四类 Guardrail 必须独立实现并进入新生产路径：

### 11.1 Plan Guardrail

检查：

- 目标是否在金融只读范围；
- Skill 和 Capability 是否已注册；
- 是否读取了超出目标所需的用户数据；
- 预算是否合理；
- 是否重复执行已成功且幂等的步骤。

### 11.2 Action Guardrail

检查：

- 行动类型是否启用；
- Capability 是否在本轮候选白名单；
- 参数 Schema；
- 用户权限；
- 只读边界；
- 调用次数和预算；
- 内部服务凭证是否由 Runtime 注入。

### 11.3 Data-quality Guardrail

检查：

- Observation 状态；
- 数据时效；
- Provenance；
- 覆盖率；
- 供应商冲突；
- `is_mock / data_mode`；
- 是否存在关键字段缺失；
- 外部文本注入风险。

### 11.4 Response Guardrail

检查：

- 结论是否能追溯到 Evidence；
- 是否披露数据时间和限制；
- 是否把客观研究误写成个性化适配；
- 是否产生交易执行语义或收益承诺；
- 是否泄露其他用户或完整账户数据；
- `PARTIAL / LIMITED` 是否被包装成确定结论。

`BLOCK / MODIFY / ASK_USER` 必须记录稳定 Audit Code、Rule ID 和公开理由。

## 12. API 与事件契约

### 12.1 对外 API

生产保留：

```text
POST   /api/v1/chat/stream
GET    /api/v1/conversations
GET    /api/v1/conversations/{session_id}
DELETE /api/v1/conversations/{session_id}
POST   /api/v1/agent-runs
GET    /api/v1/agent-runs/{run_id}
POST   /api/v1/agent-runs/{run_id}/resume
GET    /api/v1/agent-runs/{run_id}/events
GET    /api/v1/health
```

未来新增内部接口时使用 `/internal/v1`，必须通过内网和服务身份保护。

### 12.2 SSE 事件

建议稳定事件集合：

```text
run.created
run.started
run.progress
cognition.action.selected
domain.requested
domain.completed
capability.started
capability.completed
guardrail.blocked
run.interrupted
run.resumed
response.completed
run.failed
```

事件至少包含：

- `event_id`；
- `event_type`；
- `occurred_at`；
- `run_id`；
- `thread_id`；
- `request_id`（适用时）；
- `public_payload`；
- `schema_version`。

事件不得包含 Token、内部 Prompt、隐藏思维链和完整敏感账户数据。

### 12.3 错误模型

统一错误字段：

```json
{
  "code": "CAPABILITY_UNAVAILABLE",
  "message": "行情数据当前不可用",
  "retryable": true,
  "run_id": "...",
  "details": {}
}
```

对外错误信息不得泄露供应商密钥、内网 URL、SQL、堆栈或完整原始响应。

## 13. 可靠性、预算与降级

### 13.1 依赖等级

| 等级 | 依赖 | 失败行为 |
|---|---|---|
| 启动关键 | JWT 配置、生产 Checkpointer、Chat Store | 启动失败，禁止降级内存 |
| 请求关键 | LLM（模型任务）、目标 Capability | 返回结构化失败或有限结果 |
| 场景关键 | Java Data API（个性化）、MCP（行情研究） | 降级为非个性化或 `LIMITED` |
| 增强项 | Mem0、Web Search | 跳过并记录，不拖垮主链路 |

### 13.2 超时与预算

预算由 `DomainBudget` 下发并由 Runtime 统一计数：

- HTTP 建连、读取和总超时分别配置；
- 每个 Capability 有独立超时；
- 每个 Run 有总截止时间；
- 每个模型调用有 token 和时间预算；
- 超出预算停止新调用并生成 `LIMITED`；
- SSE 心跳不延长业务截止时间。

预算的具体目标值由各 Domain 的 `DomainDescriptor` 声明。以下为当前唯一实例 finance 的初始目标值（首个 Domain，非内核规范）：

> **finance 域预算实例**

| 场景 | 总预算 |
|---|---|
| 稳定知识回答 | 15 秒 |
| 单能力查询 | 30 秒 |
| 技术/基本面/估值 | 90 秒 |
| 综合研究 | 240 秒 |
| 个性化 Suitability | 120 秒 |

第二个 Domain 接入时，其预算值在该 Domain 的 `DomainDescriptor` 中声明，本表不扩大。

### 13.3 重试与熔断

- 只对明确的网络瞬态错误和 429/5xx 重试；
- 参数错误、认证错误和策略拒绝不重试；
- 指数退避并加入抖动；
- 同一供应商每次能力调用最多重试一次；
- 主备切换最多一次；
- Provider 级熔断器防止级联故障；
- 熔断状态进入指标，不写入长期用户记忆。

### 13.4 幂等与回退

幂等键至少覆盖：

- `run_id`；
- `request_id`；
- `capability_execution_id`；
- `history_id`；
- `task_id + wakeup_at`；
- Notification Outbox ID。

新 Cognitive 路径只允许在以下条件全部满足时回退旧 Root Graph：

1. 尚未执行任何 Domain Request；
2. 尚未调用外部 Capability；
3. 尚未写入 Checkpoint、History、Task 或 Notification；
4. 已记录 fallback 审计事件。

发生内部写入或外部调用后禁止自动重跑旧路径，必须结构化失败并通过原路径恢复。

## 14. 安全与隐私

### 14.1 身份

- 生产必须 `BDLH_RUNTIME_AUTH_REQUIRED=true`；
- Python 验证 Java 签发 JWT；
- `sub` 是唯一用户身份来源；
- Python 调 Java 使用内部服务凭证并显式传递已认证 user_id；
- 内部凭证至少支持轮换，长期建议升级为短期服务 JWT 或 mTLS；
- 用户请求体中的 `user_id` 仅可用于本地无鉴权测试。

### 14.2 最小权限

- Capability 默认拒绝；
- 第一阶段只注册只读能力；
- 读取账户数据前必须确认当前目标确实需要；
- LLM 上下文只包含完成目标所需的最小账户字段；
- 管理与运维接口使用独立身份和网络策略。

### 14.3 数据保护

- TLS 保护公网流量；
- 数据库连接使用独立最小权限账号；
- Secret 通过部署系统注入，不写入仓库；
- 日志对账户、Token、邮箱、手机号等脱敏；
- 备份加密并定期验证恢复；
- 用户删除会话时同步处理消息、索引和可重建派生数据；
- 长期记忆写入必须有明确策略和可删除性。

## 15. 可观测性与 SLO

### 15.1 结构化日志

每条日志包含：

- `timestamp`；
- `level`；
- `service`；
- `environment`；
- `run_id`；
- `thread_id`；
- `request_id`；
- `capability`；
- `audit_code`；
- `latency_ms`；
- `status`。

禁止记录模型隐藏思维链、Secret 和完整原始账户数据。

### 15.2 指标

至少采集：

- HTTP 请求量、延迟和错误率；
- SSE 活跃连接与断连；
- Run 完成、失败、有限和中断数量；
- 模型延迟、token 和错误；
- Capability 延迟、成功率、重试和熔断；
- MCP/Java/Web 分供应商可用率；
- Observation 覆盖率和数据时效；
- Guardrail 决策数量；
- Checkpoint、History 和 Task 写入失败；
- PostgreSQL 连接池和慢查询；
- 队列/任务积压。

### 15.3 初始 SLO

**内核 SLO**（与领域无关）：

| 指标 | 初始目标 |
|---|---|
| API 月可用性 | 99.5% |
| 健康检查 p95 | < 100 ms |
| SSE 首事件 p95 | < 2 s |
| 直接回答完成 p95 | < 15 s |
| 单能力查询完成 p95 | < 30 s |
| 跨用户数据泄露 | 0 |
| 未披露的 mock/fixture 数据 | 0 |
| 非只读外部副作用操作 | 0 |

> **finance 域实例约束：** 上述「非只读外部副作用操作 = 0」在 finance 域的具体体现是「非只读外部金融操作 = 0」（§2.3 只读约束）。finance 域复杂研究受外部供应商影响，以预算内完成率和 `PARTIAL/LIMITED` 透明度衡量，不使用单一低延迟 SLO 掩盖数据质量。第二个 Domain 接入时，其只读/副作用约束在该 Domain 的 `DomainDescriptor` 中声明。

## 16. 部署与扩缩容

### 16.1 生产部署原则

- Python 和 Java 分别构建不可变镜像；
- 容器以非 root 用户运行；
- 只读根文件系统，临时目录单独挂载；
- 健康检查区分 liveness 和 readiness；
- 配置通过环境变量或 Secret Manager 注入；
- 数据库迁移作为显式发布步骤；
- Nginx 对 SSE 关闭代理缓冲并设置合理长连接超时；
- 生产禁止使用 `latest` 镜像标签；
- MCP 和外部 LLM 版本、模型名进入发布清单。

### 16.2 多副本条件

Python Analysis 横向扩容前必须完成：

- PostgreSQL Checkpointer；
- PostgreSQL Chat Session Store；
- PostgreSQL Run Registry；
- PostgreSQL Analysis History；
- 分布式幂等控制；
- 分布式限流或边缘限流；
- SSE 重连可按 `run_id` 恢复；
- 无进程本地关键状态。

### 16.3 健康检查

`liveness` 只证明进程可服务 HTTP；`readiness` 必须检查：

- 配置合法；
- PostgreSQL 可用；
- Checkpointer 已初始化；
- Chat/Run/History Store 已初始化；
- 必需的内部服务凭证存在。

MCP、Web Search、Mem0 和外部 LLM 的短时不可用不应让进程反复重启，但必须让相关能力显示 degraded。

## 17. 生产配置基线

生产至少要求：

```text
BDLH_RUNTIME_ENV=production
BDLH_RUNTIME_AUTH_REQUIRED=true
BDLH_RUNTIME_CHECKPOINTER_BACKEND=postgres
POSTGRES_DSN=...
JWT_SECRET=...
JAVA_API_BASE_URL=http://127.0.0.1:8081
JAVA_DATA_INTERNAL_TOKEN=...
DEEPSEEK_API_KEY=...
AKSHARE_ONE_MCP_ENDPOINT=https://akshare-mcp.bdlhxny.com/mcp
CN_FINANCIAL_MCP_ENDPOINT=https://cn-financial-mcp.bdlhxny.com/sse
WEB_SEARCH_BASE_URL=http://127.0.0.1:3002
WEB_SEARCH_AGENT_ID=bdlh_runtime
WEB_SEARCH_TOKEN=...
```

要求：

- 生产启动时校验必需配置；
- 禁止使用仓库中的开发默认 JWT Secret；
- 禁止在生产自动创建 mock Java/Web 数据；
- 配置变更记录到发布审计；
- Secret 不出现在日志、异常或 `/health` 响应中。

## 18. 迁移计划

每个阶段独立开发、测试、发布和回滚。除纯契约阶段外，不合并跨阶段实施。

M0–M6 是主线，编号、范围与退出门槛不再变动；M7 为后续追加的可选阶段，只能排在主线末尾。禁止在 M0–M6 之间插入新编号。

### M0：生产基线修复

目标：先让当前路径具备可生产运行的基础。

- 持久化 Run Registry；
- 持久化 Analysis History；
- 统一 Nginx Python 路由；
- 完成 readiness；
- 明确生产禁用 mock；
- 补充结构化日志和关键指标；
- 修复部署文件中 Python 新链路与遗留 Wrapper 的冲突。

退出门槛：单副本重启后 run、thread、conversation 和 history 均可恢复。

### M1：领域边界接线（= Skill / Domain 插件边界的第一次落地）

- 将现有 `DomainRequest / Outcome` 和金融契约接入 Application；
- 实现 Finance Runtime 薄适配层；
- 抽取旧 Root Graph 中可复用的纯核心逻辑；
- 使用“核心函数 + 旧节点包装 + 新领域包装”，禁止复制两套业务逻辑；
- 隔离 Cognitive 与 Finance Checkpoint namespace。

退出门槛：新 Finance Runtime 能在不改变旧默认路径的情况下完成一次兼容股票分析。

### M2：股票研究下沉

- 实现 `StockResearchResult` 构建器；
- 建立字段来源映射；
- 将证据、冲突、覆盖率和可信度纳入输出；
- 禁止股票子图直接生成聊天文案；
- 完成旧 AnalysisResult 与新 StockResearchResult 对照测试。

退出门槛：相同 fixture 下结果字段可追溯、计算一致、限制不减少。

### M3：Suitability v0

- 已完成 Java Financial User Facts v2：鉴权确认、版本/幂等、审计和读取元数据；
- 已完成 Python 用户事实归一化：旧记录不自动升级为 LIVE，确认事实必须具备服务端确认引用；
- 已完成 `PortfolioValuationBuilder`，基于持仓与市场事实生成可追溯估值快照；
- 下一步在估值快照之上建立最小 Financial Snapshot；
- 实现确定性 Suitability 规则；
- 输出 Rule ID 和证据；
- 区分 LIVE、USER_CONFIRMED、TEST_FIXTURE、MOCK 和 UNAVAILABLE；
- 跑通“股票是否适合当前用户”的垂直场景。

退出门槛：缺关键用户数据时稳定返回 `INSUFFICIENT_INFORMATION`，不存在伪个性化结论。

### M4：Cognitive Graph 与 Communication

- 实现最小 Cognitive State；
- 接入 RESPOND、ASK_USER、INVOKE_DOMAIN；
- 实现四时点 Guardrails；
- 实现 Communication Plan 和 Response Verification；
- 与旧 Root Graph 进行影子流量和同输入对照。

退出门槛：安全覆盖矩阵无 P0/P1 缺口，故障注入和回退边界通过。

### M5：灰度切换

- 按内部用户、小比例、全量逐步灰度；
- 观察错误率、LIMITED 比例、数据覆盖、响应时间和 Guardrail 命中；
- 保留一键停止新流量能力；
- 稳定期内不删除旧路径。

退出门槛：达到 SLO，完成回滚演练，owner 批准默认路径切换。

### M6：持续任务

- 只实现一种真实观察任务；
- 建立 Task Store、Scheduler 和 Notification Outbox；
- 支持查看、取消、过期和审计；
- 唤醒后重新取数和判断；
- 通知发送具备幂等性。

### M7：插件契约验证（可选，排在主线末尾）

目标只有一个：用「新增第二个 Skill 或 Domain」证明 ADR-010 的既有契约足以支撑「只写业务、内核不动」。

说明：`SkillManifest` / `DomainDescriptor` 的字段表与首个 finance 切片已在 ADR-010 §6.1 落地（§3 登记为 `CURRENT`）。M7 **不是**再实现一遍 manifest，而是新增一个最小 Skill/Domain，验证这些既有真源可被复用且不复制 Capability Registry、Observation、Guardrail、预算或审计链。

- 只验证插件契约可用，不设业务价值目标，不承诺任何领域功能；
- 不得提前到 M6 之前执行，也不得抢占 M0–M6 的任何门禁；
- 演进阶梯与准入条件以 ADR-012 为准：当前位置是 S1（单 Domain 多 Skill），S3 / S4 不在本计划内。

退出门槛：新增一个最小 Skill 或 Domain 的过程中，Capability Registry、Observation、Guardrail、预算模型与审计链均未出现第二份实现。

## 19. 测试与发布门禁

### 19.1 测试层次

- 契约测试：所有跨层 Pydantic Schema；
- 架构边界测试：内核纯净度（认知层、领域调度、治理层、观察层不依赖领域实现，见 ADR-009 §3.3）以及 `SkillManifest / DomainDescriptor` 启动校验（`tests/architecture/test_manifest_validation.py`）；
- Domain 单元测试：指标、风险、Suitability 和覆盖率；
- Policy 测试：身份、权限、四时点 Guardrails；
- Adapter 契约测试：MCP、Java、Web；
- Graph 测试：路由、中断、恢复和预算；
- API 测试：JWT、用户隔离、SSE 和错误模型；
- 持久化测试：重启恢复、多副本和幂等；
- 故障注入：超时、429、5xx、数据库瞬断和供应商冲突；
- 对照测试：旧路径 vs 新路径；
- 安全测试：跨用户访问、Prompt Injection、敏感日志；
- 负载测试：SSE 并发、连接池、外部依赖限额。

### 19.2 必须阻断发布的条件

- 生产仍使用内存 Checkpointer、Run Registry、History 或 Chat Store；
- `auth_required=false`；
- mock 数据能进入真实个性化结论；
- 四时点 Guardrails 未接入但新 Cognitive 路径被设为默认；
- Nginx 未将 Python Agent API 路由到 Python 服务；
- 外部失败被包装为成功；
- Checkpoint 恢复存在跨用户访问；
- 数据库迁移不可回滚或未验证；
- 关键 Secret 使用默认值；
- 新路径发生写入后仍可能自动回退并重复执行。

## 20. 当前生产阻塞项

根据 2026-08-10 代码审计，以下问题必须在生产架构切换前解决：

| 阻塞项 | 当前状态 | 目标阶段 |
|---|---|---|
| Run Registry 仍为内存 | 未完成 | M0 |
| Analysis History 仍为内存 | 未完成 | M0 |
| Nginx 未统一代理全部 Python Agent Run 路径 | 需核对/修复 | M0 |
| 本地 Compose 仍以 Java + stock-wrapper 为主 | 与目标不一致 | M0 |
| Cognitive Graph 未实现 | 未完成 | M4 |
| Finance Runtime 尚未进入默认流量 | M1 独立开发完成；受 M0 发布门禁阻塞 | M5 |
| StockResearchResult 尚未进入默认流量 | M2 Builder 开发与回归完成；受 M0/M5 发布门禁阻塞 | M5 |
| PortfolioValuationBuilder 尚未进入默认生产路径 | M3 切片已完成，能力已注册；仍需完成最小 Financial Snapshot、SuitabilityEngine 及对应发布门禁 | M3/M5 |
| SuitabilityEngine 未实现 | 依赖估值快照与最小 Financial Snapshot，规则尚未实现 | M3 |
| 四时点 Guardrail 只有接口骨架 | 未完成 | M4 |
| Toolset 尚未覆盖 Suitability Planner | M1/M2 Research Planner 已接入；M3 用户事实读取与元数据已落地，估值及 Planner/Runtime 尚未接入 | M3 |
| Task/Scheduler 未实现 | 未完成 | M6 |
| 生产多副本幂等与 SSE 恢复未验证 | 未完成 | M0/M5 |

这些阻塞项不影响现有代码作为开发和迁移基线，但在完成前不得宣称最新目标架构已经生产落地。

## 21. 生产完成定义

第一阶段统一生产架构完成必须同时满足：

1. 用户请求首先进入 Cognitive Graph；
2. Cognitive Graph 只启用经过 Policy 允许的行动；
3. Finance Runtime 是金融能力唯一入口；
4. 股票研究产生结构化 `StockResearchResult`；
5. Suitability 使用真实或明确缺失的用户状态；
6. 四时点 Guardrails 全量生效；
7. Capability Registry 是唯一能力真源；
8. 所有外部数据经过 Observation Normalizer；
9. 所有金融计算可复现；
10. 最终回答引用证据并披露限制；
11. 身份、用户隔离和只读边界通过安全测试；
12. Checkpoint、会话、运行索引和历史全部持久化；
13. 新旧路径对照、故障注入、灰度和回滚演练完成；
14. API/SSE 保持兼容；
15. SLO、日志、指标和告警已上线；
16. 旧 Root Graph 尚未删除，但已不再承接默认流量；
17. Letta 和 Node Stock Skill 不在生产关键路径；
18. 运维手册、数据迁移、回滚步骤和 owner 已记录。

## 22. 历史文档处置

| 文件 | 新定位 |
|---|---|
| [`docs/archive/`](../archive/README.md) | 历史档案归档（5 个历史架构版本、7 个旧 Java 链路时期图、3 个旧提案）；只用于追溯，不指导开发 |
| [`00-BDLH-Agent-Runtime生产开发实施Prompt.md`](../prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md) | 唯一生产开发执行 Prompt，不能覆盖本文生产决策 |
| [`04-Runtime定位升级修改意见.md`](../reviews/04-Runtime定位升级修改意见.md) | 定位升级的修改意见与待执行清单，不是权威架构；已批准结论以 ADR 形式生效，冲突时以本文为准 |
| [`01-BDLH-Agent-Runtime定位与Skill扩展说明.md`](./01-BDLH-Agent-Runtime定位与Skill扩展说明.md) | 定位与扩展面说明，用于对外表述与新人理解；不是生产决策来源，不得重复或覆盖本文分层与迁移计划 |
| `README.md`（仓库根） | 入口导航与技术栈概览，2026-08-11 已按本文定位重写；只做索引，不承载决策 |
| [`00-BDLH-Agent-Runtime仓库文件管理树.md`](../00-BDLH-Agent-Runtime仓库文件管理树.md) | 文件归属与落盘规则的唯一索引；只管文件位置，不产生架构决策，冲突时以本文为准 |

历史档案和实施 Prompt 不得再以“唯一有效生产架构”指导开发。新增生产架构决策应更新本文或新增 ADR，并在本文登记。

## 23. ADR 登记

### 23.1 已批准 ADR

| ADR | 主题 | 状态 |
|---|---|---|
| [ADR-009](./ADR-009-Runtime-Domain-Skill定位与命名.md) | Runtime / Domain / Skill 三层定位与命名 | `APPROVED` |
| [ADR-010](./ADR-010-SkillManifest与DomainDispatcher契约.md) | Skill Manifest 与 Domain Dispatcher 契约 | `APPROVED`（字段表已冻结，descriptor/manifest 切片已落地；零对外行为变更） |
| [ADR-011](./ADR-011-Memory分层与晋升边界.md) | Memory 五层分层与记忆晋升边界 | `APPROVED` |
| [ADR-012](./ADR-012-多Skill与多Agent演进门槛.md) | 多 Skill 与多 Agent 演进门槛 | `APPROVED` |
| [ADR-013](./ADR-013-RAG作为可插拔KnowledgeSkill的边界.md) | RAG 作为可插拔 Knowledge Skill 的边界 | `APPROVED`（边界生效，实施未排期） |

### 23.2 已起草未批准 ADR

| ADR | 主题 | 状态 |
|---|---|---|
| [ADR-004](./ADR-004-Suitability-v0规则阈值与校准.md) | Suitability v0 规则阈值与校准 | `PROPOSED`；未由业务/风险负责人批准前，生产规则集装配必须失败关闭，禁止使用示例阈值 |

### 23.3 待补 ADR

以下决策需要在对应实现阶段补充独立 ADR，但不得阻塞本文作为总体生产基线：

1. ADR-001：PostgreSQL Run Registry 与 Analysis History 表结构；
2. ADR-002：Cognitive/Finance Checkpoint namespace；
3. ADR-003：Capability Execution 幂等键；
4. ADR-005：Scheduler、Task Store 与 Notification Outbox；
5. ADR-006：服务间认证从共享 Token 升级到短期 JWT 或 mTLS；
6. ADR-007：多副本 SSE 恢复与事件存储；
7. ADR-008：旧 Root Graph 退役门槛和删除计划。
