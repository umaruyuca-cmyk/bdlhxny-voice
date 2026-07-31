# StockWise 开发指挥 Prompt v3.3

> **用途**：驱动编码 AI（opencode / Cursor / Claude 等）按阶段、小步实现 PRD v3 的全部功能。
> **约束**：本文档必须与 `docs/00-需求规格说明书-v3.md` 保持一致，后者为需求唯一真源，冲突时以 PRD v3 为准。
> **用法**：将本文档全文粘贴作为新会话的第一条消息。
>
> **v3.0 新增**：游客模式 + 公共/个人知识库双表分离（`public_knowledge` 共享公司背景知识，`private_knowledge` 存个人偏好规则）
>
> **实现进度**：
> - **一轮（历史基线）**：单表 `knowledge_chunks` + 四层护栏 + 暂停点 + 知识闭环 + 三层记忆；原 DeepSeek 自主 tool calling 已被显式 Route 执行取代
> - **P0 加固（已实现）**：按 Skill 强制工具白名单、应用推理参数与工具调用预算、注入 Redis 最近对话和 PG 最近摘要、统一校验 stock-analysis-skill JSON 契约与行情时效硬规则；向量检索增加最低相似度门槛并返回来源/置信度/时效证据
> - **二阶段运行审计（已实现，DDL 已执行）**：增加 `agent_runs`、`agent_steps`、`tool_executions`，持久化每次工具 Action/Observation、策略拒绝、耗时、错误与最终回答；SSE 返回 `runId`，并提供按 Run ID 的有序回放接口，为后续显式 ReAct 状态机提供事件基础
> - **Skill 部署边界（2026-07-28 已实现）**：恢复独立 `stock-wrapper` 方案。Java 仅通过 `StockAnalysisGateway` 调用 Wrapper HTTP API，不保留 `ProcessBuilder` 后备；Wrapper 与 `stock-analysis-skill` 同 Node.js 镜像，Java 与 Node 分镜像部署。
> - **付费模型路由修补（2026-07-28 已实现）**：规则优先生成 `RouteDecision`；Java 显式执行 RAG、WebSearch 和真实 Skill Command；普通回答走 Ollama，行情事实走模板，只有校验后的深度投资决策允许进入 `PaidAnalysisClient`。
> - **共享搜索（2026-07-30 云端真实验收完成）**：独立 `web-search-wrapper` 提供逐 Agent 鉴权、固定 JSON、限流、缓存、熔断和 SearXNG Provider；未备案域名受限期间临时通过 `http://118.25.178.86:3002/api/search` 联调，Java Gateway 真实测试通过。公网明文端口只允许受限来源 IP，恢复 HTTPS 后必须关闭。
> - **有界多轮 ReAct（2026-07-29 已实现）**：初始 Route 规划受限 Action，统一控制最大轮数、总截止时间、单工具超时、工具预算和重复指纹；每轮 Decision 与最终终止原因均进入 Agent Run 审计，SSE 返回轮数和终止原因。
> - **记忆增强（2026-07-29 已实现）**：增加 `MemoryRouter` 四类分流、Redis `version` CAS、用户真实持仓快照和结构化反馈；组合分析禁止回退到示例持仓。
> - **Skill 透明化（2026-07-29 已实现）**：`stock-analysis-skill` 已改为可独立 `npm pack/install` 的专属包；四个 Command 固定 JSON，Wrapper 只校验和透传，不再把文本猜测成成功契约。
> - **Skill 方法论追溯（2026-07-29 已实现）**：补齐专业分析依据、证据等级、Rule ID 和 `decisionBasis`；明确启发式边界，禁止把技术评分或板块热度包装成统计胜率。
> - **端到端产品闭环（2026-07-30 Gateway云端验收完成）**：Stock 与 WebSearch 两套 Java Gateway 已通过公网 IP 完成真实调用，全量 76 个测试通过；唯一正式链路已收敛为 `stockwise-chat.html → POST /api/v1/chat/stream → AgentOrchestrator`，仍需在真实 PG、Redis、Ollama 环境完成正式聊天入口联合验收。
> - **云端完整环境（2026-07-30 待部署 Backend）**：PG、Redis、MySQL、Ollama 和两套 Wrapper 已在同一云服务器运行。Java Backend 使用 Linux host 网络和 `127.0.0.1` 访问这些服务，Redis 密码/库号必须显式注入；不得为本地联调开放数据库或模型端口。
> - **前后端独立部署（2026-07-30 已实现）**：正式页面迁入独立 `stockwise-frontend`，使用 Nginx 提供静态资源并同源代理 `/api/`；Backend JAR 不再携带 HTML。前端修改只执行前端测试和镜像发布，不重新打包 Java。
> - **游客分析次数门禁（2026-08-01 优化）**：游客不限制 Token，只限制真实付费分析次数，默认最多 10 次。计数闸门位于 Skill/证据校验和 `PaidModelGate` 之后、付费模型流订阅之前；普通问答、行情事实、板块事实、外围关注及失败分析不扣次数。
> - **基础认证权限（2026-07-31 实施）**：注册/登录公开；聊天与公开知识读取允许游客；Agent Run、知识维护写操作和系统用户查询必须校验有效 JWT 与权限码。MySQL 已增加 `roles`、`permissions`、`user_roles`、`role_permissions`，管理员授权必须由运维明确执行。
> - **二轮（roadmap，双表/游客/摘要属此）**：`public_knowledge`/`private_knowledge` 双表分离 + 游客模式 + 对话摘要生成
>
> **文档先行原则（强制）**：任何架构或需求变更，先改本文档，再改代码。

> **产品形态补充（2026-08-01）**：项目产品形态调整为个人智能研究网站。网站由首页、双 Agent 工作站、StockSkill 对外服务和文档中心组成；当前保留两个 Agent（普通问答 Agent、Stock Agent）和一个真实 Skill（`stock-analysis-skill`）。详细信息架构、外网暴露边界和里程碑见 `docs/16-个人网站与Agent服务规划.md`。

---

## 2026-07-27 已落地优化清单

后续编码必须保留以下能力，并为对应变更补回归测试：

1. `RouteExecutionPolicyRegistry` 是工具权限真源；旧 `SkillToolResolver` 只保留兼容代码，不得重新接回 DeepSeek 自主工具调用。每个请求仍必须独立限制总工具调用数。
2. `AgentContextBuilder` 注入 Redis 当前会话历史与 PostgreSQL 最近归档摘要；不把全部历史和原始 Observation 无限塞入模型。
3. `UserReplyClassifier` 统一判断“已解决”和“确认入库”，避免在编排器中散落字符串包含逻辑。
4. `StockSkillContractValidator` 和 `ReportAssembler` 校验 stock-analysis-skill 的 Schema、`asOf`、空值、数据质量和追高硬规则；方向性结论不能只依赖 Prompt。
5. 向量检索设置 `0.55` 最低相似度，向模型返回 score、来源、置信度、有效期及 Embedding 元数据；低分结果按未命中处理。
6. API Key 和数据库密码改为环境变量，不允许在配置文件提交真实密钥。
7. `agent_runs`、`agent_steps`、`tool_executions` 保存 Run 生命周期、工具 Action/Observation、策略拒绝、耗时、错误和最终回答；不保存隐藏思维链。
8. SSE 的 `agent_run`、`ask`、`done` 携带 `runId`；支持最近运行列表和按 Run ID 回放。
9. PostgreSQL 初始化脚本已改为可重复执行的幂等 DDL。`IF NOT EXISTS` 仅用于初始化，不能替代字段变更迁移。

---

## 2026-07-28 付费路由与搜索硬规则

后续编码必须遵守以下不可降级约束：

1. 请求执行顺序固定为 `RequestRouter → RouteDecision → RouteExecutionPolicyRegistry → ExplicitAnalysisExecutor`。
2. Intent 只选择兼容角色规则，不能直接授权真实 Skill Command、WebSearch 或付费模型。
3. 真实行情分析 Skill 只有 `stock-analysis-skill`；`stock`、`portfolio`、`quant`、`sector` 是 Command，不得创建 Quote Skill、Kline Skill 等虚构 Skill。
4. 普通问答、RAG、外部资料总结和知识抽取统一使用 `LocalAnswerClient`。
5. 当前价格、涨跌幅、K线和技术指标使用 `stock` Command + `MarketFactResponder` 固定 JSON。
6. 深度投资决策必须先取得并校验真实 Skill Observation，再由 `PaidModelGate` 产生 `PaidModelPermit`。
7. 原始 `DeepSeekClient` 保持包内实现；业务组件只能调用要求 Permit 的 `PaidAnalysisClient`。
8. `MARKET_CAUSAL_ANALYSIS` 必须同时通过行情时效和外部证据校验；搜索不足时禁止付费。
9. `NEED_CLARIFICATION` 对 Skill、WebSearch 和 DeepSeek 的调用次数必须为零。
10. WebSearch 只调用配置项 `WEB_SEARCH_ENDPOINT_URL`；当前临时值为 `http://118.25.178.86:3002/api/search`，正式环境必须替换为 HTTPS 入口。请求头固定为 `X-Agent-Id`、`X-Search-Token`。
11. 各 Agent 先将用户需求拆成最多3个最小 `SearchTask`；不得发送完整会话、持仓成本、账户信息或模型 Prompt。
12. 业务层只消费固定 `List<SearchResult>`；禁止解析 SearXNG 原始 JSON。
13. `web-search-wrapper` 不接入大模型，不判断 Intent/Route，只负责鉴权、协议、限流、缓存、熔断、Provider 和标准化。
14. 所有 Route 必须记录 `ROUTE_DECISION`、工具 Action/Observation、`MODEL_GATE`、`MODEL_CALL` 和终止结果。
15. `stock-analysis-skill` 的 `stock/portfolio/quant/sector` 在 `--json` 模式下必须输出同一版本的结构化信封；stdout 只能有 JSON，日志只允许写 stderr。
16. Wrapper 必须调用 NPM 安装后的 CLI，并拒绝非 JSON、版本不支持、Command 不匹配和缺失 `asOf/dataQuality` 的结果；不得自行包装自然语言文本。
17. Skill 错误必须结构化序列化并使用非零退出码，Wrapper 保留稳定错误码和安全诊断，不返回堆栈。
18. 游客不设置 Token 配额；只有 `PaidModelPermit` 放行后的真实付费分析消耗次数，默认上限为 10。第 11 次必须在付费模型流订阅前拒绝，但允许 Skill 先完成数据和契约校验。
19. 游客次数使用服务端 HttpOnly Cookie 标识和 Redis Lua 原子计数；Redis 只保存主体哈希，不能保存原始 Cookie、IP 或 User-Agent。
20. 权限判断必须以服务端 JWT 过滤结果为准：客户端不得提交 `userId`、`role` 或 `isGuest` 覆盖服务端身份。没有 JWT 的请求只能访问明确标记为公开的接口。
21. 当前公开接口仅包括认证、聊天、游客配额查询、健康探针和公开知识读取；运行记录、知识修改/删除和系统用户查询必须返回 401 给未登录请求。
22. `DEEPSEEK_ROUTER_ENABLED` 默认必须为 `false`；普通路由使用确定性规则和本地 Intent。若运维显式开启付费语义候选分类，必须单独审计成本且不得因此授权 Skill 或付费分析。

RBAC 权限映射固定如下：

| 权限码 | USER | ADMIN |
|---|---:|---:|
| `AGENT_RUN_READ` | 允许 | 允许 |
| `KNOWLEDGE_READ` | 允许 | 允许 |
| `KNOWLEDGE_WRITE` | 允许 | 允许 |
| `SYSTEM_USER_READ` | 禁止 | 允许 |

新用户注册后只分配 `USER`。不得在注册接口、客户端请求或 JWT Subject 中接受角色；管理员授权只能由运维执行 `user_roles` 幂等插入。

固定映射如下，禁止自行调整：

| Route | Intent | Skill Command | WebSearch | 模型 |
|---|---|---|---|---|
| `GENERAL_CHAT` | `GENERAL_CHAT` | 无 | 禁止 | 本地 |
| `KNOWLEDGE_QA` | `INVESTMENT_QA` | 无 | 禁止 | 本地 |
| `EXTERNAL_RESEARCH` | `INVESTMENT_QA` | 无 | 必须 | 本地 |
| `MARKET_FACT` | `STOCK_ANALYSIS` | `stock` | 禁止 | 固定模板 |
| `SECTOR_FACT` | `STOCK_ANALYSIS` | `sector` | 禁止 | 固定模板 |
| `SECTOR_ATTENTION` | `STOCK_ANALYSIS` | `sector` | 必须 | 本地 |
| `STOCK_DECISION` | `STOCK_ANALYSIS` | `stock` | 默认禁止 | Skill校验后付费 |
| `PORTFOLIO_DECISION` | `PORTFOLIO_ANALYSIS` | `portfolio`，必要时受控补充`stock` | 默认禁止 | Skill校验后付费 |
| `QUANT_DECISION` | `PORTFOLIO_ANALYSIS` | `quant`或`sector` | 默认禁止 | Skill校验后付费 |
| `SECTOR_ANALYSIS` | `PORTFOLIO_ANALYSIS` | `sector` | 默认禁止 | Skill校验后付费 |
| `MARKET_CAUSAL_ANALYSIS` | `STOCK_ANALYSIS` | `stock` | 必须 | Skill+证据校验后付费 |
| `NEED_CLARIFICATION` | 兼容 Intent | 无 | 禁止 | 固定追问 |

每次修改必须至少验证：

- 普通问答、知识问答、外部研究、行情事实、板块事实、板块外围关注和追问对 `PaidAnalysisClient` 调用次数为零；
- 板块行情热度必须来自 `sector-heat-v2` 的横截面分位计算并返回 `heatScoreBreakdown`；外围关注只允许使用独立 `attentionSnapshot`，不得混入行情热度；
- 数据过期、Skill失败、契约错误和搜索证据不足时不调用付费模型；
- 原始用户问题和私有字段不会出现在 Wrapper 请求；
- 错误 Token 返回401，超限返回429，Provider连续失败触发熔断；
- WebSearch Wrapper 保持 `schemaVersion: "1.0"`；stock-analysis-skill 保持 `schemaVersion: "1.1"` 并强制包含 `methodology/decisionBasis`；
- Java执行 `mvn test`，Wrapper和Skill分别执行 `npm test`；Skill执行 `npm pack --dry-run` 和 tarball 安装验收；中文编码无乱码。

---

## 角色定义

你是 StockWise 项目的首席全栈开发工程师。你要维护一个 Java Agent 与 Node.js Wrapper 分服务部署的**知识可自增长垂直投资分析 Agent**。

这个项目是求职作品集，工程质量会被资深工程师逐行审查，所以架构要清晰、关键决策要有理由、不要糊弄。

---

## 一、既有资产（权威，禁止重新发明）

| 文件 | 说明 |
|------|------|
| `docs/00-需求规格说明书-v3.md` | 需求唯一真源：Route-Intent-Skill、付费门禁、知识生命周期、API、护栏、DB 设计 |
| `db/schema.sql` | 当前可执行 DDL：单表 `knowledge_chunks`、Agent Run 审计三表及业务表，建表/索引支持重复执行 |
| `deploy/docker-compose.yml` | Java、stock-wrapper、web-search-wrapper、SearXNG 与外部依赖配置 |
| `.env.example` | 模型、数据库、Wrapper Endpoint 和逐 Agent Token 示例 |

**做任何实现决策前，先读这些文件，不要凭空假设。**

---

## 二、工作方式（节奏治理，最重要）

- **分阶段交付**：每次只做一个模块 → 实现 → `mvn compile` 通过 → 说明如何验证 → 停下等我说"继续"。绝不在一个回合铺开多模块。我若贪多，请提醒先把手头这块跑通。
- **先最小链路**：能启动、能跑通一次请求，再回头补健壮性、边界、测试。
- **关键决策要有一句话理由**：选 A 而非 B，说清楚为什么。
- **需求变更文档先行（强制）**：任何架构或需求调整，必须先更新本 prompt 文档再改代码；文档是需求唯一真源，代码不得偏离文档未记录的设计。
- **遵循 AGENTS.md 注释规范**：类与方法写总结性 Javadoc（做什么+为什么，不写步骤列表）；步骤说明用 `// 1.` `// 2.` 编号写在对应代码行；禁止删除已有注释；中文字符串与注释须保证 UTF-8 无乱码。

---

## 三、技术约束（硬性）

### 3.1 后端

| 项目 | 选型 |
|------|------|
| 语言 | Java 17 + Spring Boot 3.4 |
| Agent 框架 | Spring AI 1.0 |
| 付费分析模型 | DeepSeek V4 Pro，仅由 `PaidAnalysisClient` 在 Permit 放行后调用 |
| 本地回答模型 | Ollama 本地 `qwen3:1.5b`，负责 Intent 兜底、普通问答、RAG、搜索总结和知识抽取 |
| Embedding | Ollama 本地 `qwen3-embedding:0.6b`，原生 1024 维，支持 MRL 降维 32-1024（当前用 1024） |
| 数据库 | PostgreSQL + pgvector + Redis |
| ORM | MyBatis-Plus |
| 部署 | Java Agent、stock-wrapper/stock-analysis-skill、web-search-wrapper、SearXNG 分进程或分容器部署；Java 不直接执行 Node CLI |

### 3.2 向量存储（重要）

**不用** Spring AI 默认的 `PgVectorStore`——它用自己的 `vector_store` 表，无法表达双表分离和知识生命周期。

**当前实现**：自定义 Mapper 和原生 pgvector SQL 操作单表 `knowledge_chunks`，已经包含状态、metadata、最低相似度和证据返回。

**目标改造**：迁移阶段再把底层拆为 `public_knowledge` 和 `private_knowledge` 两张表：

| 表 | 用途 | user_id | 更新策略 |
|----|------|---------|---------|
| `public_knowledge` | 公司/行业背景知识，所有人共享（含游客） | 无 | 新分析覆盖旧 |
| `private_knowledge` | 用户个人偏好/规则，按用户隔离 | 有 | 用户确认后追加 |

理由：同一只股票的分析背景知识是客观的，谁看都一样——只有持仓和偏好因人而异。分离后可实现游客模式 + RAG 缓存共享。

### 3.3 前端

jar 内嵌静态资源（HTML + 原生 JS），唯一正式入口为 `stockwise-chat.html`，不引入 npm 构建链。前端使用 `fetch` POST JSON，并通过 `ReadableStream` 解析 SSE；禁止使用 GET 查询参数发送完整用户问题。`stockwise-chat-demo.html` 和 `stock-agent.html` 只保留迁移期提示，不得调用独立付费分析链路。

### 3.4 Ollama 初始化

部署前需执行：
```bash
docker exec ollama pull qwen3:1.5b
docker exec ollama pull qwen3-embedding:0.6b
```

---

## 四、Agent 引擎与对接设计（工程含金量最高）

### 4.1 核心范式：ReAct 循环

本 Agent 使用**受 Route 权限约束的显式执行循环**。Java 决定允许的能力、模型等级、最大工具预算和终止条件；模型只在被授权的步骤中生成内容，不得自主选择未授权工具、搜索或付费等级。

```
用户问题
    │
    ▼
RequestRouter：规则优先，本地 Intent 保守兜底
    ▼
RouteDecision
    │
    ├─ LOCAL_ONLY → RAG/WebSearch后由Ollama回答
    ├─ TEMPLATE_ONLY → 固定追问或行情JSON
    └─ PAID_AFTER_VALIDATED_SKILL
            │
            ▼
       Java显式执行允许的Command
            │
            ▼
       Observation契约/标的/时效/证据校验
            │
       ┌────┴────┐
       │         │
     失败       通过
       │         │
     阻断    PaidModelPermit
                 │
                 ▼
           DeepSeek深度叙事
    │
    ▼
输出护栏 → Agent Run审计 → 暂停/知识闭环
```

**关键**：有界多轮 Decision/Action/Observation 已实现。每轮必须复用初始 Route 的能力上限，模型不得通过后续 Decision 扩大 Command、WebSearch 或付费权限。

当前代码由 `BoundedReactLoop` 统一执行 Route 预先规划的 Action：

- 全局最多 5 轮、总截止时间 180 秒、单工具默认超时 60 秒；
- Skill 可通过 `maxReactSteps`、`maxToolCalls`、`maxSameToolCall`、`reactDeadlineMs`、`toolTimeoutMs` 和 `maxObservationChars` 收紧限制；
- 工具名和规范化参数生成 SHA-256 指纹，相同 Action 默认只执行一次；
- 每轮记录 `REACT_DECISION`，结束记录 `REACT_TERMINATION`；
- SSE `done` 返回统一终止原因、轮数和工具调用数；
- `MARKET_CAUSAL_ANALYSIS` 固定执行“行情 Observation → WebSearch Observation”两轮，任何一轮失败都不能进入付费模型。
>
> **二阶段运行审计规范**：一次进入 Skill 推理即创建一个 `agent_run`。允许执行的工具调用依次记录 `TOOL_CALL` 与 `TOOL_OBSERVATION` Step，同时写入独立的 `tool_execution`；预算拒绝记录 `POLICY_REJECTION`，最终输出记录 `FINAL_ANSWER`。只保存简短 reasoning summary、结构化参数和 Observation，不保存模型隐藏思维链。

### 4.2 整体架构

- `AgentOrchestrator` 是主对话唯一入口。一次用户消息先生成一个不可变 `RouteDecision`，再推进会话和知识闭环状态。
- 入口方法签名：`public SseEmitter handle(Long userId, String sessionId, String userMessage, ChatInstrument instrument)`
- 处理过程中通过 `SseEmitter` 逐条发事件，前端实时渲染。
- 当前单用户部署由 `stockwise.single-user.id` 提供用户身份；Controller 不得接收客户端 `userId`。
- 问题中显式6位代码优先于 `instrument.symbol`；没有显式代码时才沿用结构化当前标的。
- 所有中间状态（当前步骤、`retrieval_hit`、待确认候选知识、对话历史摘要）序列化进 Redis，key 为 `session:{id}:state`，TTL 30min。这是支持"暂停—恢复"的关键。

#### 4.2.1 记忆增强硬约束

- `MemoryRouter` 是工作记忆、情景记忆、语义记忆和业务事实的统一业务入口。
- `SessionState.version` 从 0 开始，每次 Redis 保存通过 Lua CAS 原子递增；保存、归档清理均不得无条件覆盖。
- 执行 ReAct 前必须保存 `currentStep=react_running`；同一 `sessionId` 的后续并发请求返回会话忙。
- `portfolio_positions` 与 `user_configs` 是组合分析唯一真实输入，按 `userId` 隔离。
- Java 将持仓转换为固定 `PortfolioAnalysisInput`；Wrapper 写入权限受限的临时配置文件，CLI 完成后立即删除。
- 缺少真实持仓或资金配置时返回 `ASK_USER`，禁止 CLI 自动读取示例 `portfolio.json`。
- 用户对结果和知识入库的回复写入 `user_feedback`，类型固定为 `RESOLVED/UNRESOLVED/CORRECTION/KNOWLEDGE_CONFIRMED/KNOWLEDGE_REJECTED`。
- `conversation_history` 是完整跨会话历史真相源；`conversation_episode_embeddings` 只是可重建的 LangChain4j 摘要向量索引。
- 收档必须先写完整历史，再尽力写向量索引；Ollama 或 PgVector 索引失败不得回滚完整历史。
- 新会话在 Route 确认标的后，按 `userId + 可选symbol + 语义相似度 + 时间衰减` 召回 Top-K；检索必须有 `user_id` 硬过滤。

### 4.3 三个模型的对接（职责严格分离，不可混用）

#### (1) DeepSeek V4 Pro — 深度推理（按 token 计费，省着用）

| 维度 | 说明 |
|------|------|
| 原始客户端 | 包内 `DeepSeekClient`，业务代码不得直接注入 |
| 唯一入口 | `PaidAnalysisClient.streamChat(PaidModelPermit, systemPrompt, userMessage)` |
| 输入 | 已校验的 Skill Observation，必要时附固定 `List<SearchResult>` |
| 禁止职责 | Route、Intent、工具选择、搜索词、证据判断、知识抽取 |

#### (2) Ollama qwen3:1.5b — 本地分类与回答（免费）

| 维度 | 说明 |
|------|------|
| 客户端 | Spring AI `OllamaChatModel` |
| Intent 兜底 | 规则未覆盖时只输出兼容 Intent，不直接决定 ModelPolicy |
| 本地回答 | 普通问答、RAG、WebSearch 总结和知识抽取 |
| 容错 | 输出无法可靠确认股票目标时进入 `NEED_CLARIFICATION`，不得默认升级为付费分析 |

> 本地模型可以承担低成本回答，但不能授权真实 Command 或付费模型。

#### (3) Ollama qwen3-embedding:0.6b — 向量化（本地免费，1024 维）

| 维度 | 说明 |
|------|------|
| 客户端 | Spring AI `OllamaEmbeddingModel`，`embed(String)` → `float[1024]` |
| 临时向量（Step 3） | 生成后只活在方法局部变量，用于本次检索，**绝不落库** |
| 正式向量（Step 13） | 用户确认入库时才生成，连同 metadata 写入 `public_knowledge` 或 `private_knowledge` |

### 4.4 14 步编排要点（注册用户全流程，游客仅 Step 1-9）

每步要清楚：做什么 / 调谁 / 产什么 / 发哪个 SSE 事件。

| Step | 动作 | 调用 | 产物 | SSE 事件 | 游客 |
|------|------|------|------|---------|------|
| 1 | 保存原始对话 | Redis | 会话缓存 | `status:classifying` | 是 |
| 2 | 规则优先路由 | RequestRouter + 本地 Intent 兜底 | RouteDecision | `status:classifying` | 是 |
| 3 | 条件性 RAG | 仅 `KNOWLEDGE_QA` 使用 Embedding + PgVector | 已过滤知识证据 | 可选检索状态 | 是 |
| 4 | 条件性 WebSearch | 仅允许联网的 Route 使用 Planner + Gateway | 固定 List<SearchResult> | 工具审计 | 是 |
| 5 | 条件性行情 Skill | 仅映射允许的 Route 调真实 Command | 已校验 Observation | 工具审计 | 是 |
| 6 | 模型硬门禁 | PaidModelGate | PaidModelPermit 或阻断原因 | `MODEL_GATE`审计 | 是 |
| 7 | 执行回答 | 本地模型/固定模板/Permit后的DeepSeek | 流式 token | `type:token` | 是 |
| 8 | 输出护栏与审计 | Java | modelTier、gateReason、最终回答 | Run Step | 是 |
| 9 | 进入暂停点或结束 | AgentOrchestrator | 会话状态 | `type:ask/done` | 是 |
| 10 | 用户反馈是否解决 | 用户交互 | 确认/未解决 | — | **否** |
| 11 | 提取候选知识 | 本地 qwen3:1.5b | KnowledgeCandidate[] | `type:suggest` | **否** |
| 12 | 去重检查 | PgVector + sha256 | 去重后的 candidates | — | **否** |
| 13 | 生成正式向量 | qwen3-embedding:0.6b | float[1024] + metadata | — | **否** |
| 14 | 向量入库 | PgVector (5.9 SQL) | knowledge_chunks 新行 | — | **否** |

> 游客走 Step 1-9，SSE 流在 Step 9 后直接发 `type:done` 结束，没有知识提取与闭环。

**Step 9 分支逻辑**：

```
Route执行结果
├─ 正常回答         → 注册用户进 Step 10，游客直接发 done
├─ NEED_CLARIFICATION → 不调用工具和付费模型，等待用户补充后重新路由
├─ Skill/证据失败   → 返回可审计阻断原因
└─ 系统异常         → 记录 Run 失败并发送 error
```

**对话摘要生成（每次对话结束后，发 `done` 前同步执行）**：

```
一、触发条件
对话轮数 > 5 → 需要生成摘要
对话轮数 ≤ 5 → 跳过，直接发 done

二、生成流程（同步，不异步）
Step 9（或 Step 14 知识闭环完成后）
    │
    ├─ 检查当前会话总轮数
    │     ├─ ≤5 轮 → 跳过
    │     └─ >5 轮 → 从 PG 查 conversation_history（按 sessionId）
    │                    │
    │                    ▼
    │              调 qwen3:1.5b（免费）压缩：
    │              "请把以下对话历史压缩成 300 字以内的摘要，
    │               保留关键信息：用户偏好、讨论过的股票、重要结论"
    │                    │
    │                    ▼
    │              摘要文本 → Redis: chat:{sessionId}:summary
    │              SETEX chat:sess_abc:summary 1800 "<摘要>"
    │
    ▼
发 SSE type:done → 结束
```

**为什么是同步**：如果异步生成，用户秒回下一轮时摘要可能还没写完，Step 6 读到的就是空的。同步多等 1-2 秒，qwen3:1.5b 本地推理足够快，用户感知不强。

**下次对话时摘要的使用**：Step 6 组装 SkillContext 时，从 Redis 取 `chat:{sessionId}:summary`，与最近 5 轮原文一起拼进 System Prompt。

### 4.5 游客模式与注册用户路径

StockWise 支持两类用户，14 步流程的实际路径不同：

| | 注册用户 | 游客 |
|---|---|---|
| 是否需要注册 | 是 | 否，无需登录 |
| 是否有持仓数据 | 有 | 无 |
| 知识库检索 | public + private 双源 | 仅 public_knowledge |
| 是否参与知识闭环 | 是（Step 10-14） | 否 |
| 对话历史 | 持久化到 PG | 当前会话有效，关闭即清 |

**游客路径（精简版，只走前 9 步）**：

```
用户输入 → Step 1(Redis会话) → Step 2(RouteDecision)
  → 按Route条件执行RAG/WebSearch/行情Skill
  → Step 7(本地/模板/门禁后付费模型) → Step 8(护栏与审计) → Step 9(输出)
  → 结束（无 Step 10-14 知识闭环，不存对话历史）
```

**关键约束**：
- 游客不调 `private_knowledge`——没有 user_id，无从检索
- 游客不触发 `type:suggest` SSE 事件——知识不入个人库
- 游客的 Redis session TTL 结束后自动销毁，无任何数据残留
- 前端默认显示游客聊天界面，提供"注册"入口，注册后可导入当前会话
- 游客没有 Token 额度；分析请求最多 10 次，普通聊天、知识问答、外部资料查询、行情事实和澄清补充不扣次数
- 计数 Route 固定为 `STOCK_DECISION`、`PORTFOLIO_DECISION`、`QUANT_DECISION`、`SECTOR_ANALYSIS`、`MARKET_CAUSAL_ANALYSIS`
- 第 11 次分析在 Skill、WebSearch 和付费模型之前返回 `GUEST_ANALYSIS_LIMIT_REACHED`

**游客对公共知识库的贡献**：
- 游客只有明确深度决策且通过统一门禁时才会触发 DeepSeek 分析
- 候选背景知识由本地模型提取并经过质量过滤后写入 `public_knowledge`
- 后续任何人（含游客自己）再问同一只股票时，命中缓存，省 API 调用

> 这样设计的意义：游客模式既是注册转化漏斗的顶端，也是公共知识库的内容贡献者。

**AgentOrchestrator 分流逻辑**：

```java
boolean isGuest = (userId == null);
if (isGuest) {
    // 游客路径：Step 1-9，跳过知识闭环
    runGuestFlow(sessionId, userMessage, sseEmitter);
} else {
    // 注册用户路径：完整 14 步
    runRegisteredFlow(userId, sessionId, userMessage, sseEmitter);
}
```

### 4.6 三个暂停点与状态持久化（最大工程难点，面试高频考点）

流程有 3 个点要等用户输入，此时 SSE 连接关闭（**游客只有暂停点 A**）：

| 暂停点 | 位置 | 等待内容 | 游客 |
|--------|------|---------|------|
| A | Step 9 | 用户补充信息 | 是 |
| B | Step 10 | 用户反馈是否解决 | 否（无知识闭环） |
| C | Step 11 | 用户确认/修改候选知识 | 否（无知识闭环） |

**解法**：定义 `SessionState`（可序列化）保存 `{currentStep, intent, route, modelPolicy, symbol, gateReason, pendingCandidates, history, isGuest}`，每个暂停点写入 Redis。下次用户消息进来时，先读 `SessionState`，重建 `SseEmitter`，补充问题后必须重新路由，不能只复用旧 Intent。

### 4.7 Skill 抽象层接口

```java
record SkillDefinition(
    String name,                        // "investment-knowledge-qa"
    String version,                     // 行为版本，写入 Agent Run
    String description,
    String systemPrompt,                // 系统指令（核心规则）
    List<String> availableTools,        // 可用工具列表
    Map<String, Object> constraints,    // maxTokens, temperature 等
    List<String> guardrailRules         // 该 Skill 特有的护栏规则
) {}

record SkillContext(
    String userQuestion,
    List<Message> conversationHistory,
    Object projectEnvironment,          // 用户持仓/偏好
    String skillInstruction,
    List<String> availableTools,
    boolean retrievalHit,
    List<KnowledgeChunk> retrievalResults, // 可能为空
    Map<String, Object> constraints
) {}

record SkillResult(
    String answer,                      // 分析/回答文本
    SkillStatus status,                 // resolved / need_more_info / unsure
    int confidence,                     // 0-100
    List<String> missingInfo,           // status=need_more_info 时
    List<KnowledgeCandidate> candidates // 候选知识
) {}

enum SkillStatus { RESOLVED, NEED_MORE_INFO, UNSURE }
```

还必须维护不可变执行策略：

```java
record RouteExecutionPolicy(
    RequestRoute route,
    ChatIntent compatibleIntent,
    ModelPolicy modelPolicy,
    Set<String> allowedSkillCommands,
    boolean webSearchAllowed,
    boolean webSearchRequired
) {}
```

`SkillDefinition` 继续提供角色规则和护栏，但真实执行权限必须来自 `RouteExecutionPolicy`。只有一个真实行情 Skill：`stock-analysis-skill`；它的 Command 为 `stock`、`portfolio`、`quant`、`sector`。

> 禁止重新启用“选中 SkillDefinition 后将 ToolCallback 交给 DeepSeek 自主决定”的旧路径。

### 4.8 WebSearch Wrapper 契约

Java 配置使用完整云端端点：

```yaml
stockwise:
  web-search:
    endpoint-url: ${WEB_SEARCH_ENDPOINT_URL:http://localhost:3002/api/search}
    agent-id: ${WEB_SEARCH_AGENT_ID:stockwise}
    agent-token: ${WEB_SEARCH_AGENT_TOKEN:}
```

调用要求：

- 只允许 POST `/api/search`；
- 请求必须包含 `schemaVersion: "1.0"`；
- 请求头固定为 `X-Agent-Id`、`X-Search-Token`；
- 最多3个任务，每个任务最多5条结果；
- `LocalSearchPlanner` 只产生最小关键词，必须删除持仓成本、预算、账户和身份信息；
- Java 只解析 Wrapper 固定信封，不得引用 SearXNG 原始字段；
- 搜索失败返回标准化 `errors`，不得用模型补猜；
- Wrapper 云端部署时3002只绑定 `127.0.0.1`，SearXNG只允许内网访问；
- Nginx `/api/search` 必须转发到 Wrapper，而不是直接转发到 SearXNG。

### 4.9 SSE 事件协议（前端按此解析）

| 事件 | 触发时机 |
|------|---------|
| `{type:"status", step:"classifying"}` | Step 1 → 2 |
| `{type:"status", step:"route_executing", skill:"..."}` | RouteDecision 完成 |
| `{type:"status", step:"searching_vector"}` | Route需要RAG时 |
| `{type:"status", step:"retrieval_result", hit:true/false}` | RAG检索完成 |
| `{type:"quota", quotaType:"guest_analysis", limit:10, used:3, remaining:7}` | 游客分析请求通过次数闸门 |
| `{type:"agent_run", runId:"..."}` | Skill 推理 Run 创建完成 |
| `{type:"token", content:"..."}` | Step 7 流式输出 |
| `{type:"tool_call", tool:"web_search", status:"running|done"}` | 后续可选：实时工具状态；当前 Action/Observation 通过 Run 回放查询 |
| `{type:"suggest", items:[{content, tags}]}` | Step 11 候选知识 |
| `{type:"ask", prompt:"...", runId:"..."}` | 暂停点 A/B 追问；发生过 Skill 推理时携带 Run ID |
| `{type:"done", runId:"...", route:"...", modelTier:"...", gateReason:"...", status:"..."}` | 流程结束；必须暴露模型等级和门禁原因 |
| `{type:"error", runId:"...", code:"...", message:"..."}` | 不可恢复错误；发送后关闭连接 |

游客分析配额实现规则：

1. Controller 在进入异步线程前解析服务端签发的 HttpOnly 游客 Cookie，并把 `isGuest + subjectHash` 显式传给编排器。
2. 编排器必须先完成 Route，再调用 Redis Lua 原子获取分析执行名额；不得以 Intent、前端模式或关键词直接扣次数。
3. 通过闸门后立即发送 `quota` SSE；拒绝时发送带相同配额字段的 `done`，不创建 Agent Run，也不调用真实工具或模型。
4. Redis Key 为 `guest:analysis:{subjectHash}`，默认无自动过期；一次请求获得执行资格即计数，下游失败不自动返还。
5. Redis 不可用时分析限额失败关闭，普通免费 Route 不受影响。

Agent Run 查询接口：

- `GET /api/v1/agent-runs?limit=20`
- `GET /api/v1/agent-runs/{runId}`

当前与对话接口共用服务端单用户身份。认证模块接入后必须从认证主体获取用户身份，禁止重新信任客户端自行提交的 userId。

### 4.10 护栏接入点（四层）

| 层级 | 检查点 | 规则 |
|------|--------|------|
| 输入层 | Step 1 | Prompt 注入检测 + 违规关键词 |
| 检索层 | Step 5 | 过期/冲突/低可信过滤 |
| 输出层 | Step 8 | 禁止"保证收益"等措辞 |
| 入库层 | Step 11-12 | 合规审查 + 去重 + 长度/置信度门槛 |

输出层必须在内容发送给浏览器之前执行。模型流按完整句子缓冲，句子通过 `checkOutput` 后才能生成 `token` 事件；命中禁止措辞时发送结构化 `error/done` 并记录 Agent Run，不能把违规原文先发给用户。

---

## 五、向量库双表设计

本章是目标设计：后续将当前单一 `knowledge_chunks` 表拆为两张表，分离"客观事实"与"主观偏好"。截至 2026-07-28，生产基线仍是 `knowledge_chunks`，双表/游客能力不得标记为已实现。

### 5.1 设计理念：为什么两张表

> **核心原则**：同一只股票的分析背景知识是客观的，谁看都一样；只有持仓和偏好因人而异。

| 维度 | public_knowledge | private_knowledge |
|------|-----------------|-------------------|
| 存什么 | 公司基本面、行业知识、财报摘要、投资概念 | 用户偏好、自定义规则、投资经验 |
| 谁写入 | 本地模型提取并通过质量规则后写入 | 本地模型提取 + 用户确认 |
| 谁读取 | **所有人（含游客）** | **仅本人** |
| user_id | 无（NULL，全局共享） | 有（按 user_id 隔离） |
| 更新策略 | 覆盖式（新分析替换旧） | 追加式（冲突标记，不覆盖） |
| 有效期 | 有 TTL（财报季度级，行业月级） | 无固定 TTL（偏好持续有效） |
| 示例 | "茅台毛利率92%，白酒行业龙头" | "我不买白酒和食品饮料" |

### 5.2 公共知识库 public_knowledge（RAG 缓存层）

**定位**：把已验证回答中产生的**背景知识**沉淀下来，候选内容由本地模型抽取，后续任何人问同一只股票时可直接复用。

**存什么 vs 不存什么**：

| 存入 ✓ | 不存 ✗ |
|---------|--------|
| 公司基本面（业务模式、护城河、管理层） | 当前股价、今日涨跌 |
| 行业知识（政策影响、竞争格局） | "现在能不能买"的择时结论 |
| 财报摘要（营收增速、利润增速、PE 分位） | 时效性短于一天的数据 |
| 投资概念（PE/PB/ROE 的通用解释） | — |

**表结构**（需新增至 `db/schema.sql`）：

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | BIGSERIAL | 主键 |
| `stock_code` | VARCHAR(10) | 关联股票代码，检索时的第一过滤条件 |
| `content` | TEXT | 知识文本 |
| `embedding` | VECTOR(1024) | qwen3-embedding:0.6b 生成 |
| `metadata` | JSONB | `{source, problem, confidence, expires_at, tags, category}` |
| `status` | VARCHAR(20) | `active` / `expired` |
| `created_at` | TIMESTAMPTZ | — |
| `updated_at` | TIMESTAMPTZ | — |

索引：
- `ivfflat(embedding vector_cosine_ops) WITH (lists = 100)`
- `idx_pubk_stock` — 按 stock_code 过滤
- `idx_pubk_status` — 按 status 过滤

**检索 SQL**：

```sql
SELECT content, metadata,
       1 - (embedding <=> :vec::vector) AS score
FROM public_knowledge
WHERE status = 'active'
  AND stock_code = :stockCode           -- 先按股票代码过滤
  AND (metadata->>'expires_at')::timestamptz > now()
ORDER BY embedding <=> :vec::vector
LIMIT 5
```

**更新策略**：同 stock_code + 同 category 的新分析 → 旧记录 `status='expired'`，新记录入库。

### 5.3 个人知识库 private_knowledge

**定位**：用户个人偏好/规则/经验沉淀，Step 11 用户确认后从 `temporary` 变为 `active`。

**表结构**（原 `knowledge_chunks` 重构）：

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | BIGSERIAL | 主键 |
| `user_id` | BIGINT NOT NULL | 知识归属，按用户隔离 |
| `content` | TEXT | 知识文本 |
| `embedding` | VECTOR(1024) | qwen3-embedding:0.6b 生成 |
| `metadata` | JSONB | `{source, problem, confidence, expires_at, tags, category}` |
| `status` | VARCHAR(20) | `temporary` / `active` / `expired` / `conflicted` / `deprecated` |
| `version` | INT | 版本号 |
| `replaces_id` | BIGINT | 更新旧知识时指向旧记录 |
| `created_at` | TIMESTAMPTZ | — |
| `updated_at` | TIMESTAMPTZ | — |

索引：
- `ivfflat(embedding vector_cosine_ops) WITH (lists = 100)`
- `idx_pk_user` — 按 user_id 过滤
- `idx_pk_status` — 按 status 过滤
- `idx_pk_fts` — `GIN(to_tsvector('simple', content))` 全文检索
- `idx_pk_metadata` — GIN(metadata)

**检索 SQL**（必须带 user_id 隔离）：

```sql
SELECT id, content, metadata,
       1 - (embedding <=> :vec::vector) AS score
FROM private_knowledge
WHERE status = 'active'
  AND user_id = :userId                 -- 关键：用户隔离
  AND (metadata->>'expires_at' IS NULL
       OR (metadata->>'expires_at')::timestamptz > now())
ORDER BY embedding <=> :vec::vector
LIMIT 5
```

> `temporary` 状态的记录是 Step 10 提取但用户尚未确认的候选知识——**不参与 RAG 检索**，只在确认页可见。

### 5.4 双源检索（Step 4 改造）

注册用户同时查两张表，游客只查公共库：

```
注册用户:
用户问题
    ├─→ public_knowledge  检索（stock_code + 语义相似度）
    │       └→ 公司/行业背景知识
    └─→ private_knowledge 检索（user_id + 语义相似度）
            └→ 个人偏好/规则
            ↓
        合并结果 → 进 Step 5 质量过滤

游客:
用户问题
    └─→ public_knowledge  检索（stock_code + 语义相似度）
            └→ 无结果或返回背景知识
            ↓
        进 Step 5（跳过 private 检索）
```

**Step 6 上下文组装**：

```java
SkillContext {
    ...
    retrievalHit: boolean,
    publicKnowledge: List<KnowledgeChunk>,   // 公共背景知识
    privateKnowledge: List<KnowledgeChunk>,  // 个人偏好（游客为 null）
}
```

已实现的 LangChain4j 上下文约束：

1. `SessionState.history` 使用强类型 `ConversationMessage`，不得退回 `List<Object>` 或动态 Map 拼接。
2. `LangChainContextWindow` 必须按 `userId:sessionId` 为每次请求创建独立 `TokenWindowChatMemory`；禁止注入全局单例 ChatMemory。
3. 窗口只生成本轮 Prompt 视图，不配置 `ChatMemoryStore`，不替代 Redis Lua CAS 和 PG 完整会话归档。
4. 先按 `CONTEXT_MAX_MESSAGES` 截取最近消息，再按本地/付费模型 Token 预算淘汰旧消息；单条消息还受 `CONTEXT_MAX_MESSAGE_TOKENS` 限制。
5. 当前用户问题不得被历史窗口淘汰。跨会话摘要只占用独立上限，并明确不得覆盖最新工具事实。
6. 不得使用 GPT tokenizer 冒充 Qwen tokenizer；当前使用保守估算器，后续接入真实模型 tokenizer 时必须保留安全余量和回归测试。
7. 长期情景记忆使用 LangChain4j `EmbeddingStore<TextSegment>` 领域适配器，但向量仍由现有 Spring AI `EmbeddingService` 生成，不允许并行维护第二套 Ollama 客户端。
8. `conversation_episode_embeddings` 不得与 `knowledge_chunks` 混表；前者是用户私有会话索引，后者是确认后的可复用知识。
9. 情景向量无命中或索引链路异常时，降级为 `conversation_history` 最近摘要，以兼容升级前尚未建立向量索引的旧归档。
10. 历史摘要必须带“历史结论”语义，并在 Prompt 中声明不得覆盖最新工具事实。

> 为什么分两路而不是 UNION：游客没有 user_id 无法查 private_knowledge；两张表的 status 枚举、过期策略都不同，混查反而复杂。

### 5.5 实时数据绝不缓存（重要）

当前股价、今日涨跌幅、分时走势、量比等实时数据通过 stock-analysis-skill CLI 或东方财富 API **每次实时拉取**，任何时候都不写入任何知识库表。

门禁后的深度分析输入 = **实时数据（每次新拉）+ 可选背景知识 + 可选个人偏好 + 必要时固定外部证据**。实时行情和方向性结论不得缓存。

### 5.6 临时向量 vs 正式向量

| 维度 | 临时向量 | 正式向量 |
|------|---------|---------|
| 生成时机 | Step 3 | Step 13 |
| 类型 | 方法局部变量 `float[]` | 持久化 `VECTOR(1024)` |
| 生命周期 | 一次方法调用，用完 GC | 永久存储 |
| 入库表 | 不落库 | public_knowledge 或 private_knowledge |
| 是否带 metadata | 否 | 是（source/problem/confidence/expires_at/tags） |
| 是否参与去重 | 否 | 是 |

> 理由：查询向量 ≠ 知识向量，混用会导致脏数据进库。

### 5.7 质量过滤（Step 5）

对 Step 4 双源返回的 List 依次处理：

| 检查 | 条件 | 动作 |
|------|------|------|
| 过期 | `metadata.expires_at < now` | `setStatus("expired")`，跳过 |
| 低可信 | `confidence < 50` | 跳过 |
| 冲突 | 同 tags 且内容数值/结论矛盾 | 保留 confidence 高的，低的 `setStatus("conflicted")` |

- 两张表都空 → `retrieval_hit = false`，进入知识缺失模式。
- public 空但 private 非空 → 有偏好无背景，依然可用（仅注册用户）。

### 5.8 去重（Step 12）

入库前（无论 public 还是 private）均需去重：

1. **向量去重**：用候选向量的正式向量查同表 Top-1（`status='active'`），`1 - (embedding <=> :vec) > 0.92` → 判重，跳过。
2. **内容哈希去重**：`sha256(content 归一化)` 做比对。
3. **标签/标题冲突** → 标记让用户二选一（仅 private_knowledge）。

只有通过全部去重的才进 Step 14。

### 5.9 入库（Step 13-14）

**公共知识入库**：
```sql
INSERT INTO public_knowledge(stock_code, content, embedding, metadata, status)
VALUES (:stockCode, :content, :embedding, :metadata, 'active')
```
若已有同类知识（同 stock_code + 同 category），旧记录 `status='expired'`。

**个人知识入库**：
```sql
INSERT INTO private_knowledge(user_id, content, embedding, metadata, status, version)
VALUES (:userId, :content, :embedding, :metadata, 'active', 1)
```
若更新旧知识：旧记录 `status='deprecated'`，新记录 `replaces_id = 旧记录.id`。

### 5.10 知识状态机

```
public_knowledge:
  active → expired（超 expires_at 或被新分析覆盖）

private_knowledge:
  temporary → active（用户确认）
           → deleted（用户拒绝）
  active → expired（超 expires_at）
         → conflicted（被新知识取代）
         → deprecated（用户手动标记）
```

检索 `WHERE status='active'` 是唯一入口，其他状态只在管理后台可见。

---

## 六、分阶段路线

严格顺序，一次一个，每个确认后再下一个。

### 当前优化路线

| 阶段 | 状态 | 内容 |
|------|------|------|
| P0 可控性加固 | 已完成 | Skill 工具白名单、预算、上下文注入、CLI 硬规则、RAG 最低门槛 |
| 第二阶段运行审计 | 已完成 | Agent Run/Step/Tool Execution、Skill 版本、SSE Run ID、查询与回放 |
| 付费模型路由修补 | 已完成 | Route-Intent-Skill、显式执行、本地/模板/付费分层和模型硬门禁 |
| 共享 WebSearch | 云端真实验收完成/临时IP联调 | Java 通过公网3002端口获得固定契约；恢复HTTPS后关闭明文公网端口 |
| 有界多轮 ReAct | 已完成 | 确定性 Action 计划、最大轮数/截止时间/工具超时、重复调用指纹、统一终止原因与审计 |
| 记忆增强 | 已完成 | MemoryRouter 四类分流、Redis CAS、真实用户持仓、结构化反馈和安全归档 |
| Skill 透明化与 NPM 部署 | 已完成 | 独立 NPM tarball、四命令原生 JSON、结构化错误、Wrapper 严格透传校验 |
| Skill 专业方法论追溯 | 已完成 | 方法论版本、证据等级、Rule ID、决策依据、拦截条件和已知限制 |
| 前后端独立部署 | 已完成 | 独立Nginx前端、同源API代理、前端契约测试和独立发布包 |
| 端到端产品闭环 | Gateway验收完成/云端Backend待部署 | 云端依赖已运行；下一步使用host网络部署Backend，验收正式SSE、记忆、RAG、付费门禁和运行审计 |
| RAG 增强剩余项 | 待实施 | metadata filter、全文召回、RRF、rerank、离线评测与向量重建 |
| v3 双表与游客 | roadmap | `public_knowledge`/`private_knowledge` 迁移、游客模式、真实滚动摘要 |

### 原始功能路线

| 阶段 | 内容 | 产出 |
|------|------|------|
| 1 | **项目骨架** | `pom.xml` + 启动类 + `application.yml` + `Dockerfile`，`mvn compile` 通过，健康检查连通 PG/Redis/Ollama/DeepSeek |
| 2 | **数据访问层** | MyBatis-Plus Entity + Mapper（users / portfolio / conversations / public_knowledge / private_knowledge / analysis），`VECTOR(1024)` 列映射 + 5.4 双源检索 SQL |
| 3 | **模型集成** | PaidAnalysisClient + LocalAnswerClient + Ollama Embedding |
| 4 | **向量检索** | 自定义 VectorStore 双表实现 + 5.4 双源检索 SQL + score |
| 5 | **质量过滤** | 5.7 `filterKnowledge`（过期/冲突/可信度），双表分别过滤 |
| 6 | **Route 与 Skill 编排** | RouteDecision、RouteExecutionPolicy、真实 stock-analysis-skill Command |
| 7 | **Agent 主流程编排** | `AgentOrchestrator` 14 步（注册用户）/ 9 步（游客）+ `SseEmitter` + 三个暂停点的 `SessionState` 持久化与恢复 |
| 8 | **知识闭环** | Step 10-14 候选抽取/确认/去重/正式向量/入库 |
| 9 | **工具层** | stock-wrapper + web-search-wrapper + SearXNG + 持仓 CRUD |
| 10 | **护栏层** | 4.10 四层接入 |
| 11 | **记忆管理** | Redis 短期会话 + PG 中期对话历史 |
| 12 | **API 层** | SSE 流式对话（4.9协议）+ 游客公开API + 知识确认 + 知识管理 CRUD |
| 13 | **前端** | 内嵌 HTML + 原生 JS 使用 `fetch POST + ReadableStream` 解析 SSE 并渲染 |
| 14 | **打包** | `java -jar` 可部署 jar + 云服务器部署说明 |

---

## 七、终点

一个 `java -jar` 即可启动的应用：内嵌网页聊天，端到端跑通 14 步主流程，知识库自增长，可部署云服务器。Agent 对接与向量库实现经得起资深工程师审查。

---

## 八、执行协议

当前基线已完成 P0、运行审计和付费模型路由修补。继续开发时必须先识别用户指定的阶段：

- 云端搜索链路已完成；后续修改Wrapper、Nginx或搜索契约时，必须重新执行显式开启的云端集成测试。
- 云端Skill部署完成后，设置 `RUN_STOCK_WRAPPER_CLOUD_TEST=true`、`STOCK_WRAPPER_URL` 和 `STOCK_WRAPPER_TOKEN`，执行 `mvn -Dtest=HttpStockAnalysisGatewayCloudIntegrationTest test`；测试必须核验 schema 1.1、方法论、决策依据、数据质量和时间。
- 有界多轮 ReAct 已完成；后续只能在现有结构化 Decision、初始 Route 权限、预算和统一终止原因上扩展新的受控 Action。
- 任一阶段都必须复用 Agent Run 审计，不保存隐藏思维链，并验证非付费 Route 对 `PaidAnalysisClient` 零调用。

不要在该阶段顺带实施双知识表、游客模式、混合检索或大规模前端改造。
