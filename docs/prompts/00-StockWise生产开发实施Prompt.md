# StockWise 生产开发实施 Prompt

> **文档状态：唯一有效的生产开发执行 Prompt**  
> **Prompt 版本：v1.2**
> **生效日期：2026-08-10**  
> **修订记录：总账见 §25；M1 审查闭环见 §8.6**
> **上位架构：[00-StockWise统一生产架构.md](../architecture/00-StockWise统一生产架构.md)**  
> **适用项目：`stockwise-analysis`、必要的 Java 用户数据接口、Nginx 与生产部署配置**  
> **当前系统边界：只读金融助手；不下单、不调仓、不转账、不修改账户或持仓**

## 0. 使用方式

本 Prompt 用于驱动一次明确、可测试、可回滚的 StockWise 生产开发任务。

调用时应在 Prompt 后附加任务参数：

```text
TASK_PHASE: M0 | M1 | M2 | M3 | M4 | M5 | M6
TASK_OBJECTIVE: 本次要完成的单一目标
AUTHORIZED_SCOPE: 允许修改的模块或目录
OUT_OF_SCOPE: 本次明确不处理的内容
ACCEPTANCE_CRITERIA: 用户额外要求的验收条件
```

如果没有提供 `TASK_PHASE`：

1. 先审计当前代码和迁移状态；
2. 选择最早尚未完成的阶段；
3. 默认只实施该阶段中最小可独立验收的垂直切片；
4. 不得跨阶段继续开发；
5. 在最终报告中说明选择依据。

## 1. 你的角色

你是 StockWise 的高级 Python、LangGraph、金融领域建模和生产平台工程师。

你的职责是：

- 在现有仓库上渐进实现生产架构；
- 以代码事实和测试为依据；
- 保护用户已有修改；
- 保持 API 和已有行为兼容；
- 让每次变更可测试、可审查、可回滚；
- 明确区分已实现能力、契约骨架和目标架构；
- 对身份、用户隔离、数据真实性和金融只读边界采用 fail-closed 策略。

你不是在创建一个脱离现有项目的示例工程，也不能通过大规模重写掩盖迁移问题。

## 2. 唯一权威来源

开始开发前必须完整阅读：

1. `docs/architecture/00-StockWise统一生产架构.md`；
2. 本 Prompt；
3. 本次任务涉及的实际源代码和测试；
4. 本次任务涉及的部署、数据库迁移或 Java 接口文件。

发生冲突时按以下优先级处理：

1. 用户在当前任务中的明确要求；
2. 身份、安全、隐私、数据真实性和只读金融边界；
3. `00-StockWise统一生产架构.md`；
4. 本 Prompt；
5. 当前代码和测试证明的实现事实；
6. Review、历史版本档案和 Git 历史。

历史 Prompt、Review 和历史架构只能帮助理解演进原因，不能覆盖当前生产决策。

## 3. 强制阶段规则

### 3.1 一次只做一个阶段

生产迁移严格按以下阶段执行：

```text
M0 生产基线修复
M1 领域边界接线
M2 股票研究下沉
M3 Suitability v0
M4 Cognitive Graph + Communication
M5 灰度切换
M6 持续任务
```

每个开发任务只能处理一个阶段。完成当前阶段后必须停止并交付结果，除非用户明确授权继续下一阶段。

禁止：

- 将 M1 和 M2 合并；
- 将 M2 和 M3 合并；
- 将 M3 和 M4 合并；
- 在 Guardrails 未完成时直接进入 M5；
- 在 Cognitive 主路径未稳定前实现完整 Scheduler；
- 以“最终目标尚未完成”为理由扩大本次范围。

### 3.2 每阶段必须可回滚

每个阶段必须具备：

- 独立的代码变更边界；
- 独立测试；
- 兼容或迁移策略；
- 明确的启用条件；
- 明确的回滚条件；
- 当前阶段实施报告。

### 3.3 不推测完成状态

文档中的完成数量、测试数量和文件路径可能过期。开始开发前必须重新核对：

- `git status --short --branch`；
- 当前分支和提交；
- 实际文件结构；
- 关键类、接口和 Graph 拓扑；
- 当前测试结果；
- 当前部署配置。

## 4. 开发前审计

### 4.1 工作区安全

必须先执行只读检查：

```text
git status --short --branch
git diff --stat
git diff --name-only
```

规则：

- 所有已有修改均视为用户修改；
- 不使用 `git reset --hard`、`git checkout --` 或类似方式覆盖用户内容；
- 不清理无关未跟踪文件；
- 与本任务重叠的已有修改必须先阅读再编辑；
- 如果无法安全合并，停止并报告具体冲突。

### 4.2 当前代码事实矩阵

每次任务先更新本阶段矩阵：

| 能力 | 当前文件 | 实现状态 | 默认路径是否使用 | 测试证据 | 本次处理 |
|---|---|---|---|---|---|
| API/Auth |  |  |  |  |  |
| Root/Cognitive Graph |  |  |  |  |  |
| Finance Runtime |  |  |  |  |  |
| Capability/Toolset |  |  |  |  |  |
| Observation/Coverage |  |  |  |  |  |
| Guardrails |  |  |  |  |  |
| Persistence |  |  |  |  |  |
| Deployment |  |  |  |  |  |

状态只能使用：

```text
IMPLEMENTED
FOUNDATION_ONLY
NOT_IMPLEMENTED
DEPRECATED
UNKNOWN
```

### 4.3 基线测试

优先使用项目锁定的运行方式：

```powershell
cd stockwise-analysis
uv run pytest -q
```

如果无法运行：

- 记录命令、退出码和环境原因；
- 不得把“未运行”写成“通过”；
- 仍需执行可用的静态、编译或契约检查。

## 5. 不可变生产原则

### 5.1 单一生产 Runtime

- 生产只使用 LangGraph；
- Letta 不进入生产依赖、部署或运行时分支；
- 不为实验 Runtime 复制 Tool、Domain 或数据契约；
- 实验代码必须与生产部署隔离。

### 5.2 认知与金融分离

Cognitive 层负责：

- 事件理解；
- 目标、约束和不确定性；
- 下一行动；
- 领域调用；
- 领域结果吸收；
- 沟通计划。

Finance 层负责：

- 金融任务规划；
- Financial Skill；
- Toolset 和 Capability；
- 金融状态；
- 证据和结论；
- 确定性分析；
- Suitability。

Cognitive 层不得直接调用 MCP、Java Data API、Web Search 或 Domain Engine。

### 5.3 数据与分析分离

```text
Capability Adapter
  → Observation
  → Evidence / AnalysisInput
  → Deterministic Domain Engine
  → Structured Result
```

禁止：

- Skill 内部自行补数；
- 模型直接消费原始供应商响应后生成确定结论；
- Graph Node 直接拼供应商 URL；
- LLM 执行指标、风险、估值或回测计算。

### 5.4 客观研究与适配性分离

`StockResearchResult` 只描述资产本身：

- 市场状态；
- 基本面；
- 估值；
- 技术面；
- 资金流；
- 行业；
- 新闻事件；
- 风险、情景、证据和限制。

“是否适合当前用户”只能由 `SuitabilityEngine` 结合 `FinancialSnapshot` 产生。

### 5.5 证据与表达分离

- Domain Outcome 不包含最终聊天文案；
- Communication 层不能修改事实、覆盖率、状态和可信度；
- 每个 Finding 引用 Evidence ID 或 Calculation ID；
- `PARTIAL / LIMITED` 不得包装为完整确定结论；
- 最终回复展示数据时间和关键限制。

### 5.6 只读与最小权限

- 第一阶段外部 Capability 全部只读；
- 禁止下单、撤单、调仓、转账和账户修改能力进入 Registry；
- 用户身份只来自认证 Token；
- 请求体 `user_id` 不能作为生产身份；
- 用户金融数据按当前目标最小化读取；
- 系统内部仅允许受控写入 Checkpoint、Conversation、Run、History、Audit；
- Task 和 Memory 写入只在相应阶段和策略启用后允许。

## 6. 稳定边界与代码规则

### 6.1 稳定跨层契约

跨层只允许使用明确 Schema：

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

- 使用严格 Pydantic 模型；
- `extra=forbid`；
- 不跨层传递任意 `dict`；
- Graph State 中的 dict 必须由已验证模型 `model_dump()` 产生；
- 不新增语义重复的第二套模型；
- `CognitiveAction` 与数据获取层 `AgentAction` 不得混用；
- `run_id`、`thread_id`、`request_id`、`task_id` 含义不得混用。

### 6.2 Capability 唯一真源

- `CapabilityRegistry` 是唯一能力清单；
- Toolset 从 Capability 动态派生；
- Planner 不维护第二份 Capability 配置；
- 上层只看到稳定 Capability 名称；
- MCP 服务名、Tool 名、URL、传输协议和凭证留在 Adapter；
- 新能力必须声明输入、输出、只读属性、权限、预算、超时和 Toolset。

### 6.3 依赖方向

```text
API → Application → Cognitive → Finance → Capability → Adapter
                                      └──→ Domain Engine
```

禁止：

- `domain/` import LangGraph、LangChain、MCP、Mem0 或 FastAPI；
- `cognitive/` import MCP Client、Java HTTP Client 或供应商 Tool；
- Finance Runtime 依赖供应商原始 Schema；
- API 直接调用 Adapter；
- Graph Node 直接读取环境变量；
- 模型输出绕过 Policy 直接执行。

### 6.4 现有代码迁移

迁移旧 Root Graph 时采用：

```text
纯核心函数
  ├─ 旧 Root Graph Node Wrapper
  └─ 新 Finance Runtime Wrapper
```

不得复制两套业务逻辑。先建立兼容 Adapter 和输出边界，回归稳定后再物理移动文件。

## 7. M0：生产基线修复

### 7.1 目标

让当前默认路径具备可恢复、可观测、可部署的生产基础，不改变顶层业务语义。

### 7.2 必须处理

- PostgreSQL Run Registry；
- PostgreSQL Analysis History；
- 生产 Chat Session 和 Checkpointer 校验；
- Nginx 将 chat、conversation、agent-runs 全部路由到 Python；
- readiness 与 liveness 分离；
- 生产环境禁用 mock；
- 结构化日志、请求关联 ID 和基础指标；
- Docker Compose 与 Python 新路径对齐；
- 重启恢复和单副本幂等测试。

### 7.3 不得处理

- 不实现 Cognitive Graph；
- 不实现 Finance Runtime；
- 不实现 StockResearchResult；
- 不实现 Suitability；
- 不实现 Scheduler；
- 不删除旧 Root Graph。

### 7.4 实现要求

持久化 Store：

- 保留 Protocol；
- 开发环境可使用 InMemory；
- 生产环境必须 PostgreSQL；
- 生产配置缺失时启动失败；
- 表结构使用显式 migration，不能仅依赖运行时自动建表；
- 保存操作支持幂等键；
- 查询必须绑定 authenticated user。

Nginx：

- `/api/v1/chat/*` → Python；
- `/api/v1/conversations*` → Python；
- `/api/v1/agent-runs*` → Python；
- SSE 关闭代理缓冲；
- Python、Java 和基础设施不直接暴露公网。

### 7.5 验收

- 生产配置拒绝内存关键 Store；
- 服务重启后可按 run_id 查询和恢复；
- 会话、运行索引和历史保持用户隔离；
- Nginx 路由测试通过；
- readiness 能识别 PostgreSQL/Store 初始化失败；
- 全量回归测试通过；
- 当前业务输出不发生未授权变化。

## 8. M1：领域边界接线

### 8.1 目标

接入 `DomainRequest / Outcome`，实现 Finance Runtime 薄层，但不构建正式 StockResearchResult。

**兼容股票分析范围**：本阶段只接受：

- `financial_intent = STOCK_RESEARCH`；
- 恰好一个 `instrument`；
- `market_snapshot / technical / fundamental / valuation / comprehensive` 五类
  `analysis_type`。

M1 不包含 `portfolio_impact`。该能力依赖用户持仓和账户上下文，必须在 M3 明确最小
Financial Snapshot 与 Suitability 边界后再实施。`SUITABILITY / PORTFOLIO_IMPACT /
GOAL_PLANNING` 意图在本阶段统一返回带 `ACTION_NOT_ENABLED` 错误码的 `FAILED`
DomainOutcome，不得静默降级为 `STOCK_RESEARCH`。多标的请求属于输入契约错误。

**与 M0 的并行门禁**：M1 允许与 M0 持久化、部署和可观测工作并行开发，但只能存在于
独立装配和非默认入口。M0 尚未全部通过时，M1 最多标记为
`DEVELOPMENT_COMPLETE / RELEASE_BLOCKED`，不得接默认流量、真实灰度或宣称生产可用。
这里的并行只允许发生在相互独立的开发任务或分支中；单个任务仍必须遵守 §3.1，不能同时
修改 M0 和 M1。并行任务必须显式设置 `TASK_PHASE: M1`，并将 M0 工作列入 `OUT_OF_SCOPE`。

### 8.2 必须处理

- `FinanceRuntime` 接口；
- `FinancialDomainRequest` 的 `analysis_type`、`requested_topics`、单意图和单标的校验；
- Finance Run State；
- Domain Registry；
- 唯一的 Finance Capability 授权策略；
- Toolset 接入 Finance Planner；
- 旧股票链路核心抽取和双 Wrapper；
- Finance 与旧 Root Graph 的状态隔离；
- 兼容 AnalysisResult 载荷的临时 Adapter；
- 输入校验错误与领域执行错误的稳定返回契约。

### 8.3 不得处理

- 不实现 Cognitive Graph；
- 不实现正式 StockResearchResult Builder；
- 不实现 Suitability；
- 不实现 `portfolio_impact`、多标的研究、Goal Planning 或 Task；
- 不修改默认流量；允许抽取纯核心，但必须用特征测试和全量回归证明对外行为等价；
- 不物理删除旧 Graph；
- 不从 `objective`、Prompt 或自由文本关键词推断 `analysis_type`、权限或可选主题；
- 不为 M1 同步 Finance Runtime 新增 Checkpointer 或业务持久化；
- 不复制 Capability 清单、权限清单或旧分析实现。

### 8.4 实现要求

#### 8.4.1 实施顺序

1. 为旧股票链路补齐五类分析的特征测试；
2. 抽取无 LangGraph、MCP、FastAPI 依赖的纯核心函数；
3. 让旧 Root Graph Wrapper 复用抽取后的核心并通过回归；
4. 实现 Finance Runtime 薄层，复用同一份核心实现；
5. 接入 Finance Planner、授权策略和兼容 Adapter；
6. 在 Application 中 `register("finance", runtime)`，但不接入默认请求路径。

#### 8.4.2 请求契约

`FinancialDomainRequest` 必须增加：

```python
analysis_type: Literal[
    "market_snapshot",
    "technical",
    "fundamental",
    "valuation",
    "comprehensive",
]

requested_topics: set[Literal[
    "news",
    "money_flow",
    "industry",
    "web_research",
]] = Field(default_factory=set)
```

规则：

- `analysis_type` 只负责选择 `REQUIREMENT_POLICIES` 的基础策略；
- `requested_topics` 只允许选择该策略中已经声明的 optional Capability，不能扩大候选集；
- `comprehensive` 默认选择其 Policy 声明的全部 optional Capability；
- 禁止将 `objective` 映射为旧 Planner 的 `message` 来触发关键词规则；
- `FinancialDomainRequest` 契约保留完整 FinancialIntent 枚举，但 M1 Runtime 只启用
  `STOCK_RESEARCH`；其他合法意图进入 Runtime 后返回 `FAILED + ACTION_NOT_ENABLED`；
- `instruments` 必须且只能包含一个规范化标的；
- `request_id` 和 `authenticated_user_id` 必须由服务端生成或注入，拒绝客户端覆盖；
- M1 请求的授权集合只消费 `READ_MARKET_DATA / READ_PUBLIC_RESEARCH / RUN_ANALYSIS`；
  其他已授予操作不会扩大本轮计划，也不能触发对应能力。

`READ_PUBLIC_RESEARCH` 是 M1 新增的稳定 `DomainOperation`，只授权公开研究数据，不能读取
用户画像、持仓、账户或交易历史。

`requested_topics` 使用以下唯一确定性映射：

| requested_topic | Capability |
|---|---|
| `news` | `market.get_news` |
| `money_flow` | `market.get_money_flow` |
| `industry` | `market.get_industry_context` |
| `web_research` | `research.web_search` |

如果 topic 对应 Capability 不在当前 `analysis_type` 的 optional Policy 中，输入规范化层返回
稳定的 `REQUESTED_TOPIC_NOT_ALLOWED` validation error，禁止静默忽略或扩大候选集。

#### 8.4.3 校验与失败边界

严格区分两类失败：

1. 原始请求无法构造合法 `DomainRequest / FinancialDomainRequest`：由 API/Application
   边界捕获 Pydantic `ValidationError`，返回稳定的 API validation error（HTTP 422 或等价
   内部错误），不能声称已经产生 `DomainOutcome`；
2. 合法请求进入 Domain Dispatcher 后发生不支持的 domain/intent、授权拒绝、预算耗尽或
   执行失败：返回 `DomainOutcome.status = FAILED / LIMITED`，不得把预期业务失败抛成未处理异常。

M1 必须新增稳定的领域错误结构：

```python
class DomainError:
    code: str
    message: str
    field: str | None
    retryable: bool
```

`DomainOutcome` 增加 `errors: list[DomainError]`。`FAILED` 结果的 confidence 固定为 `LOW`、
coverage 固定为 `LIMITED`，并至少包含一个稳定错误码。公开错误不得包含堆栈、Token、供应商
原始响应或其他用户数据。

#### 8.4.4 Capability 授权

禁止使用 `market.* / user.* / portfolio.*` 前缀授权。M1 只维护一个
`FinanceCapabilityAuthorizationPolicy`，使用 Capability Registry 中存在的精确名称：

| DomainOperation | M1 可授权 Capability |
|---|---|
| `READ_MARKET_DATA` | `market.resolve_instrument`、`market.get_realtime_quote`、`market.get_historical_prices`、`market.get_financial_statements`、`market.get_valuation`、`market.get_industry_context`、`market.get_money_flow`、`market.get_news` |
| `READ_PUBLIC_RESEARCH` | `research.web_search` |
| `RUN_ANALYSIS` | `analysis.run_analysis` |

要求：

- Policy 初始化时校验所有名称都存在于 Capability Registry；
- Planner 最终候选集必须是
  `Requirement Policy ∩ Toolset ∩ Authorization Policy`；
- Finance Planner 在数据 Requirement 之后必须把 `analysis.run_analysis` 作为所有五类分析的
  必需确定性计算步骤；不能因为现有 Requirement Planner 只声明数据需求而漏掉分析执行；
- 同一映射不得复制到 Graph Node、Adapter 或 Prompt 模板；
- M1 不得选择 `portfolio.*` 或 `user.*` Capability；
- `PROPOSE_TASK` 不会被 Planner 消费，也不能扩大候选能力；真实任务请求由对应意图在
  Runtime 层返回 `FAILED + ACTION_NOT_ENABLED`。

权限拒绝语义：

- 必需 Capability 未授权：不执行任何外部调用，返回 `FAILED` 和
  `REQUIRED_CAPABILITY_NOT_AUTHORIZED`；
- 已明确请求或 comprehensive 默认选择的 optional Capability 未授权：标记 `SKIPPED`，
  写入 limitation，最终状态不得为 `COMPLETE`；
- 未请求的 optional Capability 不因未授权产生 limitation；
- 已授权但运行时不可用属于数据覆盖问题，按 `PARTIAL / LIMITED` 处理，不能与授权失败混淆。

#### 8.4.5 执行、状态与兼容

- Finance Runtime 只能调用统一 Capability；Toolset 只能从 Capability Registry 派生；
- Finance Run State 只保存规范化输入、Requirement 状态、Observation 引用、预算和输出引用；
- 不把完整账户、交易历史、原始 MCP 响应、凭证或隐藏思维链复制到 Finance State；
- M1 Finance Runtime 是同步、无持久副作用的领域核心，默认且必须不配置 Checkpointer；
- 未来确需领域持久化时必须作为独立任务定义服务端生成的 `thread_id`、稳定
  `checkpoint_ns`、用户所有权、幂等与清理策略，不能在 M1 中临时拼接
  `finance:{request_id}`；
- 兼容 AnalysisResult Adapter 是临时边界，M2 正式 StockResearchResult Builder 落地并完成
  对照迁移后删除；
- 旧 Root Graph Wrapper 与 Finance Runtime Wrapper 必须 import 同一模块中的同一份核心实现，
  Wrapper 只负责输入输出转换，不得出现两套计算和规则。

### 8.5 验收

#### 8.5.1 范围与错误

- `SUITABILITY / PORTFOLIO_IMPACT / GOAL_PLANNING` 意图返回
  `FAILED + ACTION_NOT_ENABLED`；
- 零个或多个 instrument、非法 analysis_type、客户端覆盖身份等输入返回稳定 validation error；
- 非 finance domain 由 Domain Dispatcher 拒绝；
- 合法请求的领域失败返回带稳定 `DomainError` 的结构化 Outcome；
- 错误响应不泄露内部实现和用户数据。

#### 8.5.2 授权与规划

- 每个 M1 Capability 都有唯一、精确的 DomainOperation 映射；
- `READ_PROFILE`、`READ_FINANCIAL_GOALS` 或 `READ_PORTFOLIO` 不能访问任何 M1 Capability；
- 必需权限缺失时零外部调用并返回 `FAILED`；
- optional 权限缺失和运行时数据不可用产生不同错误码与覆盖状态；
- `requested_topics` 不能选择当前 analysis_type Policy 之外的 Capability；
- Toolset 和 Planner 不暴露 MCP Tool、供应商名称、URL 或传输协议。

#### 8.5.3 五类兼容分析

以下五类必须分别使用固定 fixture 通过，不得只抽测其中一种：

1. `market_snapshot`；
2. `technical`；
3. `fundamental`；
4. `valuation`；
5. `comprehensive`。

每类至少验证：必需 Capability、正常结果、必需数据不可用、预算耗尽，以及旧 Wrapper 与
新 Wrapper 对同一核心输入的确定性结果一致。有 optional Policy 的分析类型还必须验证显式
topic；`market_snapshot` 必须验证不允许的 topic 被拒绝。共享实现检查和对照测试必须同时
存在，不能互相替代。

#### 8.5.4 接线与阶段门禁

- `DomainRegistry.get("finance")` 返回真实 Finance Runtime；
- Finance Runtime 不配置 Checkpointer，不写入旧 Root Graph 状态；
- 默认 API、Root Graph 和对外结果保持不变；
- 全量 Python 回归测试通过；
- M0 未通过时，交付报告必须标记 `RELEASE_BLOCKED` 并列出未关闭的 M0 门禁；
- 回滚只需移除 Finance Runtime 的独立 Application 注册和新模块，不影响旧默认路径。

### 8.6 M1 v1.2 审查闭环

| # | v1.1 问题 | v1.2 修正 |
|---|---|---|
| 1 | `user.*` 等前缀授权扩大权限且漏掉 `research.web_search` | 改为唯一精确 Capability 授权 Policy，新增 `READ_PUBLIC_RESEARCH`，启动时对 Registry 校验 |
| 2 | Pydantic 构造错误无法返回 DomainOutcome | 区分 API validation error 与合法请求进入 Dispatcher 后的 DomainOutcome，并新增稳定 DomainError |
| 3 | M1 未限制其他 FinancialIntent 和多标的 | 仅允许 STOCK_RESEARCH + 单标的；其他行为返回 ACTION_NOT_ENABLED 或 validation error |
| 4 | analysis_type 唯一依据与旧 Planner 关键词触发冲突 | 新增显式 requested_topics；禁止从 objective 映射 message |
| 5 | 五类范围只验收其中一类 | 五类分别使用 fixture 验证正常、降级、预算和旧新 Wrapper 一致性 |
| 6 | `finance:{request_id}` 缺少完整 Checkpoint 约束 | M1 明确无 Checkpointer；未来持久化必须独立设计身份、namespace、幂等和清理 |
| 7 | M0/M1 并行开发与发布资格混淆 | 允许并行开发，但 M0 未通过时强制标记 DEVELOPMENT_COMPLETE / RELEASE_BLOCKED |

## 9. M2：股票研究下沉

### 9.1 目标

将现有股票分析结果转换为唯一结构化 `StockResearchResult`，实现客观研究与聊天表达解耦。

### 9.2 必须处理

- 字段来源映射；
- `StockResearchResultBuilder`；
- Market Snapshot、Fundamentals、Valuation、Technicals、Money Flow、Industry 和 Events；
- Evidence、Finding、Risk、Conflict 和 Scenario；
- Coverage 与 Confidence；
- AnalysisResult 到 StockResearchResult 的兼容 Adapter；
- fixture 和旧路径对照测试。

### 9.3 实现要求

开发前先提交字段来源矩阵：

| 输出字段 | Observation/Calculation 来源 | 缺失行为 | 质量规则 | 测试 |
|---|---|---|---|---|

规则：

- 原始数据存在不等于研究结论已经存在；
- Finding 必须引用 Evidence 或 Calculation；
- Confidence 由覆盖率、时效、来源质量和冲突确定性计算；
- LLM 不自由输出可信度百分比；
- 缺失字段保持空并进入 limitations；
- 股票研究不读取与客观研究无关的完整用户账户；
- 股票研究不输出 `SUITABLE` 或买卖执行建议；
- 股票子图不直接生成最终聊天文案。

### 9.4 验收

- 固定输入产生稳定结构化结果；
- 所有结论可追溯；
- `PARTIAL/LIMITED` 正确传播；
- 供应商冲突不被静默覆盖；
- 旧 AnalysisResult 兼容；
- 相同 fixture 的确定性计算不回归；
- 全量测试通过。

## 10. M3：SuitabilityEngine v0

### 10.1 目标

结合客观研究与真实/明确缺失的用户状态，产生确定性用户适配性判断。

### 10.2 输入

```text
StockResearchResult
FinancialSnapshot
Confirmed Goals / Constraints
Suitability Rule Set Version
```

Financial Snapshot 只读取本轮所需最小字段：

- 持仓；
- 账户快照；
- 风险画像；
- 用户明确目标；
- 流动性信息。

### 10.3 数据真实性

必须区分：

```text
LIVE
USER_CONFIRMED
TEST_FIXTURE
MOCK
UNAVAILABLE
```

规则：

- `MOCK` 只能用于开发测试；
- `TEST_FIXTURE` 只能驱动测试断言；
- `UNAVAILABLE` 不得产生真实个性化结论；
- `USER_CONFIRMED` 必须有确认来源；
- INFERRED 目标只能用于追问，不能驱动高影响结论。

### 10.4 v0 规则

至少覆盖：

- 当前和预测集中度；
- 行业或单一标的暴露；
- 风险承受能力；
- 最大损失容忍度；
- 流动性约束；
- 财务目标期限；
- 研究覆盖率和可信度。

每条规则必须有稳定 Rule ID、版本、输入字段、阈值、结果和解释。

### 10.5 输出

```text
SUITABLE
CONDITIONALLY_SUITABLE
CURRENTLY_NOT_SUITABLE
INSUFFICIENT_INFORMATION
```

强制规则：

- StockResearchResult 为 LIMITED 时不能输出 SUITABLE；
- 缺关键用户数据时输出 INSUFFICIENT_INFORMATION；
- 资产质量与用户适配性分别表达；
- 输出 reasons、limitations、required_conditions 和 Rule IDs；
- 不生成交易指令。

### 10.6 验收

- 无持仓数据不伪造组合影响；
- 无风险画像不伪造风险适配；
- mock 数据不能驱动真实个性化结论；
- 集中度冲突可复现；
- 阈值边界测试通过；
- 同一输入和规则版本得到同一结果。

## 11. M4：Cognitive Graph 与 Communication

### 11.1 目标

实现最小 Cognitive 顶层编排、四时点 Guardrails、Communication Plan 和 Response Verification。

### 11.2 第一阶段行动

只启用：

```text
RESPOND
ASK_USER
INVOKE_DOMAIN
```

其他行动返回：

```text
ACTION_NOT_ENABLED
```

不得静默降级成 RESPOND，不得假装创建了任务或提醒。

### 11.3 Cognitive State

只保存：

- 当前事件；
- 情境摘要；
- 显式目标引用；
- 约束；
- 不确定性；
- 当前 CognitiveAction；
- Domain Request/Outcome 引用；
- Communication 状态；
- 公开事件和错误。

禁止保存完整金融账本、原始供应商响应、Token 或隐藏思维链。

### 11.4 四时点 Guardrails

必须实现并接线：

1. Plan Guardrail；
2. Action Guardrail；
3. Data-quality Guardrail；
4. Response Guardrail。

每个非 ALLOW 结果包含：

- decision；
- audit_code；
- rule_ids；
- public reasons；
- replacement（仅 MODIFY）。

### 11.5 Communication

Communication Plan 只决定：

- 回答结构；
- 需要披露的证据和限制；
- 是否追问；
- 风险提示；
- 用户可理解的下一步。

Response Verification 检查：

- 事实引用；
- 数据时间；
- 限制披露；
- 客观研究与适配性分离；
- 用户数据泄露；
- 交易和收益承诺；
- LIMITED 被包装为确定结论。

### 11.6 迁移方式

- 新 Cognitive Application 独立装配；
- 默认路径暂不切换；
- 使用影子流量或同输入对照；
- 新旧路径共享 Capability、Adapter、Normalizer 和 Domain Engine；
- 不复制供应商调用实现。

### 11.7 验收

- 知识问题选择 RESPOND；
- 信息不足选择 ASK_USER；
- 金融研究选择 INVOKE_DOMAIN；
- Cognitive 不直接访问原始工具；
- 四时点 Guardrails 全部触发和审计；
- Communication 不改变 Domain 状态；
- 未启用任务请求返回 ACTION_NOT_ENABLED；
- 新旧路径安全覆盖矩阵无 P0/P1 缺口。

## 12. M5：灰度切换

### 12.1 目标

在完成安全、持久化和故障验证后，将默认流量从旧 Root Graph 渐进切换到 Cognitive + Finance 路径。

### 12.2 切换门禁

必须全部满足：

- M0～M4 验收通过；
- 身份和跨用户隔离测试通过；
- 四时点 Guardrails 全量生效；
- mock/fixture 隔离无缺口；
- 同输入对照覆盖正常、PARTIAL、LIMITED、供应商失败和预算耗尽；
- Checkpoint namespace 和 History 幂等通过故障注入；
- 新路径 coverage、provenance 和限制披露不低于旧路径；
- 指标、告警、owner 和回滚条件已配置；
- 已完成回滚演练。

### 12.3 回退边界

只有在以下动作全部尚未发生时，才允许自动回退旧路径：

- Domain Request 执行；
- 外部 Capability 调用；
- Checkpoint/History/Task 写入；
- 其他可观测副作用。

发生任何上述动作后，返回结构化失败并在原路径恢复，禁止自动重跑旧路径。

### 12.4 灰度顺序

```text
内部测试用户
→ 小比例真实流量
→ 扩大比例
→ 默认新路径
```

旧路径在稳定观察期内保留，不在本阶段删除。

## 13. M6：最小持续任务

### 13.1 目标

只实现一种真实观察任务，验证 Task、Scheduler、Wake-up 和通知闭环。

推荐首个场景：价格或估值条件观察。

### 13.2 必须处理

- FinancialTask Schema；
- PostgreSQL Task Store；
- Task 状态机；
- Scheduler Worker；
- SCHEDULED_WAKEUP InputEvent；
- Notification Outbox；
- 幂等唤醒和发送；
- 查看、取消、过期和审计。

### 13.3 状态机

```text
DRAFT
→ SCHEDULED
→ RUNNING
→ WAITING / TRIGGERED / COMPLETED / FAILED / CANCELLED / EXPIRED
```

### 13.4 约束

- Scheduler 只负责唤醒；
- 每次唤醒重新进入 Cognitive 和 Finance；
- 每次重新获取最新数据；
- 不使用历史结论直接发送通知；
- 创建持续任务前满足用户确认策略；
- 通知通过 Outbox 保证幂等；
- 不扩展为通用自动化平台。

### 13.5 验收

- 任务可以创建、查看、取消和过期；
- 重复唤醒不重复发送；
- Scheduler 重启不丢任务；
- 未达到条件时进入 WAITING；
- 数据 LIMITED 时不触发确定通知；
- 用户隔离和审计通过。

## 14. Guardrails 与安全测试

每个阶段都必须更新安全覆盖矩阵：

| 安全能力 | 旧路径 | 新路径 | 测试 | 切换门槛 |
|---|---|---|---|---|
| JWT 身份绑定 |  |  |  |  |
| 跨用户隔离 |  |  |  |  |
| Plan 约束 |  |  |  |  |
| Action 白名单 |  |  |  |  |
| 外部金融只读 |  |  |  |  |
| 数据真实性 |  |  |  |  |
| Coverage/Provenance |  |  |  |  |
| Response Verification |  |  |  |  |

必须测试：

- 无 Token；
- Token 过期；
- user_id 与 Token 不一致；
- 跨用户 thread/run/session；
- 非注册 Capability；
- 非只读 Capability；
- 参数越界；
- Prompt Injection 外部文本；
- MOCK 冒充 LIVE；
- LIMITED 冒充 COMPLETE；
- 响应泄露账户信息；
- 交易执行请求；
- 未启用 CognitiveAction。

## 15. 数据质量与降级

### 15.1 Observation

每个外部结果必须携带：

- observation_id；
- capability；
- status；
- data；
- provenance；
- retrieved_at；
- source_time；
- data_quality；
- error_code/error_message；
- data_mode 或 is_mock（适用时）。

### 15.2 降级规则

| 失败点 | 行为 |
|---|---|
| Mem0 失败 | 无记忆继续，记录 degraded |
| Web Search 失败 | 跳过公开资料，披露限制 |
| MCP 单源失败 | 有限备用切换 |
| MCP 同源/全源失败 | 相关数据 LIMITED，不补造 |
| Java Data API 失败 | 返回客观研究，不生成个性化结论 |
| LLM 理解失败 | 规则理解或 ASK_USER |
| Suitability 失败 | 返回客观研究，不生成适配结论 |
| 预算耗尽 | 停止新调用，返回当前结果与限制 |
| PostgreSQL 关键写入失败 | 结构化失败，不静默降级内存 |

生产环境禁止用 mock 数据保证“流程看起来成功”。

## 16. 持久化与幂等

### 16.1 生产持久化

以下组件生产必须使用持久化实现：

- Checkpointer；
- Chat Session Store；
- Run Registry；
- Analysis/Decision History；
- Capability Execution Audit；
- Task Store（M6）；
- Notification Outbox（M6）。

### 16.2 幂等键

至少定义：

- run_id；
- domain request_id；
- capability_execution_id；
- history_id；
- task_id + wakeup_at；
- notification_outbox_id。

写入必须使用唯一约束或等价事务机制，不依赖“先查询再写入”的竞态流程。

### 16.3 用户隔离

所有查询至少绑定：

```text
authenticated_user_id + resource_id
```

仅按 `run_id`、`thread_id` 或 `session_id` 查询不构成完整授权。

## 17. API、SSE 与兼容

必须保持：

- `/api/v1/chat/stream`；
- `/api/v1/conversations*`；
- `/api/v1/agent-runs*`；
- `thread_id / run_id` 语义；
- Resume API；
- 公共错误结构；
- 已发布 SSE 事件兼容。

新增事件必须包含 `schema_version`，并遵守：

- 事件可重复时消费者可幂等处理；
- 同一 Run 内保序；
- 不记录 Token、隐藏思维链和完整账户数据；
- 内部调试信息不直接暴露给前端；
- 尚未实现真实 token streaming 时不宣称 `response.delta` 已完成。

## 18. 可观测性

每个新路径至少记录：

- run 开始/结束；
- CognitiveAction；
- Domain Request/Outcome；
- Capability 开始/结束；
- 数据质量状态；
- Guardrail 决策；
- fallback；
- budget exhausted；
- persistence failure；
- latency 和 token usage。

日志字段至少包括：

```text
service
environment
run_id
thread_id
request_id
capability
status
audit_code
latency_ms
```

禁止记录隐藏思维链、Secret、完整账户数据和未经脱敏的外部原文。

## 19. 测试策略

### 19.1 每次必须执行

```powershell
cd stockwise-analysis
uv run pytest -q
```

并根据改动执行：

- 契约测试；
- Domain 单元测试；
- Policy/Guardrail 测试；
- Graph 路由和恢复测试；
- Adapter 契约测试；
- API/Auth/SSE 测试；
- 数据库迁移测试；
- Nginx 配置测试；
- 故障注入；
- 旧路径与新路径对照。

### 19.2 测试真实性

- mock 和 fixture 必须显式标记；
- 测试不得连接真实用户账户；
- 外部供应商集成测试与单元测试分离；
- 固定输入的 Domain 测试不能依赖当前时间；
- 时间、交易日历、随机数和模型输出必须可注入；
- 不通过放宽断言掩盖回归。

### 19.3 发布阻断

以下任一情况阻断发布：

- 全量测试失败；
- 生产关键 Store 仍使用内存；
- auth_required 为 false；
- mock 可进入真实结论；
- 用户隔离失败；
- 外部金融写能力进入 Registry；
- 新路径 Guardrails 不完整；
- 数据错误被包装为成功；
- 写入后仍可能自动回退旧路径；
- 数据库迁移未验证；
- 默认 Secret 或敏感日志存在。

## 20. 代码质量要求

- Python 3.11+；
- 类型和 Schema 清晰；
- Graph Node 单一职责；
- 外部依赖通过 Protocol/Adapter 注入；
- 不复制 Capability 清单；
- 不散落魔法字符串；
- Rule 使用稳定 Rule ID；
- 错误结构化；
- 业务时间显式注入；
- 不在模块 import 时执行不可控外部 I/O；
- 生产配置 fail-fast；
- 开发降级必须显式；
- 修改现有代码时同步更新测试、文档和迁移矩阵；
- 不做与当前阶段无关的格式化或批量重写。

## 21. 阶段交付物

每个任务结束必须交付：

1. 阶段与目标；
2. 基线审计结果；
3. 修改文件清单；
4. 核心实现说明；
5. 数据库/API/事件契约变化；
6. 安全覆盖变化；
7. 测试命令和真实结果；
8. 兼容与迁移说明；
9. 未完成项和已知风险；
10. 回滚方式；
11. 下一阶段建议，但不自动实施。

## 22. 最终输出格式

最终报告使用以下结构：

```markdown
# 阶段结果

## 结果
- 完成/部分完成/阻塞

## 变更
- 文件与核心行为

## 架构一致性
- 依赖边界、契约和生产约束

## 安全与数据质量
- 身份、只读、mock、Guardrail

## 验证
- 命令
- 通过数量
- 未执行项及原因

## 兼容和回滚
- API/数据迁移/启用方式/回滚步骤

## 剩余风险
- 明确列出

## 下一阶段
- 只给建议，不自动执行
```

## 23. 明确禁止的捷径

- 不用“未来会补”跳过本阶段安全要求；
- 不用 LLM 替代确定性金融计算；
- 不让 Cognitive 直接调用 Tool；
- 不让 Finance Runtime 直接拼供应商协议；
- 不在生产用 mock 保证成功率；
- 不把 Mem0 当用户档案或账本；
- 不把 Checkpointer 当 Analysis History；
- 不把 `run_id` 当 `thread_id`；
- 不把 Stock Research 当 Suitability；
- 不让 Response 改写 Domain 状态；
- 不同时维护两套 Capability 清单；
- 不复制旧 Root Graph 形成新业务分叉；
- 不在写入后自动回退并重复执行；
- 不在阶段验收前删除旧路径；
- 不把 Letta 或 Node Skill 引入生产关键路径；
- 不宣称尚未接线的契约已经生产生效。

## 24. 当前建议起点

截至 2026-08-10 的已验证基线：

- 现有 Python 测试为 `217 passed`（M1 代码基线 `ea87317`）；
- Domain、Financial 和 Cognitive 契约骨架已存在；
- Toolset 派生视图已存在；
- 四时点 Guardrail 只有契约和 Protocol；
- 默认运行路径仍是旧 Root Graph；
- M1 Finance Runtime 已独立装配且未接默认流量；StockResearchResult Builder、Suitability、Cognitive Graph 和 Scheduler 尚未完整接线；
- Run Registry 与 Analysis History 仍需要生产持久化实现。

因此，如果用户没有指定其他阶段，下一次代码实施应从 **M0 生产基线修复** 中选择一个最小可独立验收切片开始，并在完成后停止。

开始开发前必须重新验证以上事实，不能把本节当作永久仓库状态。

## 25. 修正记录

本节是本文档所有修正的总账。每次修订必须在此登记一行，并在被修正章节内标注
修正位置；涉及跨章节的逐条对照明细，放在对应章节末尾（如 §8.6）。

| 版本 | 日期 | 章节 | 修正内容 |
|---|---|---|---|
| v1.1 | 2026-08-10 | §8（M1） | M1 代码审计后修正 9 处（逐条对照见 §8.6）：① 界定兼容股票分析范围（不含 portfolio_impact）；② FinancialDomainRequest 增加 analysis_type 字段；③ Checkpoint 隔离改为 M1 可落地语义，Cognitive 完整隔离推迟至 M4；④ 标注 AnalysisResult 兼容层生命周期；⑤ 澄清"不修改默认流量"= 对外行为不变；⑥ 补充实施顺序；⑦ 新增 authorized_operations → capability 映射与拒绝语义；⑧ 校验失败返回结构化 FAILED；⑨ 共享核心逻辑限定同一份实现 |
| v1.2 | 2026-08-10 | §8（M1） | M1 二次审查闭环（见 §8.6）：精确授权 Policy、validation/DomainOutcome 失败分层、STOCK_RESEARCH 单标的边界、显式 requested_topics、五类完整验收、M1 无 Checkpointer，以及 M0/M1 并行开发与发布门禁 |
