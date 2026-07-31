# StockWise Backend 架构分析

## 一句话定位

这是一个"Java 显式 Agent + Node.js 确定性金融分析服务 + RAG 知识闭环"的多服务系统。`stock-analysis-skill` 负责行情抓取和指标计算，`stock-wrapper` 提供内部 HTTP 边界，Java 通过 Route 显式执行工具、控制模型等级和付费门禁，DeepSeek 仅消费已校验的 Skill Observation 生成深度叙事，本地 Ollama 负责分类兜底、普通问答和知识抽取，PostgreSQL/pgvector 与 Redis 分别承担长期数据和短期会话状态。

## 当前组件分层

| 层 | 组件 | 主要职责 |
|---|---|---|
| 客户端 | 独立 `stockwise-frontend` Nginx 静态服务 | SSE 对话、知识 CRUD、Agent Run 回放、同源代理 `/api/` |
| API | `ChatController`、`KnowledgeController`、`AgentRunController` | 对话入口、知识接口、运行审计 |
| 路由 | `RequestRouter`、`RuleBasedRouteResolver`、`IntentClassifier`、`RouteExecutionPolicyRegistry` | 规则优先路由、本地模型兜底、Route 权限白名单 |
| 编排 | `AgentOrchestrator`、`ExplicitAnalysisExecutor`、`BoundedReactLoop` | 会话编排、Route 分发、有界工具执行 |
| 门禁 | `PaidModelGate`、`PaidAnalysisClient`、`PaidModelPermit` | Skill 校验 + 证据检查后才放行 DeepSeek |
| 工具 | `StockTools`、`StockAnalysisGateway`、`HttpStockAnalysisGateway`、`StockSkillContractValidator` | 行情执行、Wrapper HTTP 桥接、Schema/时效/追高校验 |
| 记忆 | `MemoryRouter`、`SessionStateService` | 工作/情景/语义/业务四类记忆统一入口、Redis CAS |
| 搜索 | `WebSearchGateway`、`HttpWebSearchGateway`、`LocalSearchPlanner`、`EvidenceValidator` | 独立共享搜索服务、隐私过滤、证据充分性校验 |
| 模型 | `LocalAnswerClient` (qwen3:1.5b)、`PaidAnalysisClient` (DeepSeek V4)、Ollama Embedding | 本地回答、门禁后深度推理、向量化 |
| 数据 | PostgreSQL + pgvector、Redis | 知识/历史/审计/业务实体、短期会话状态 |
| 领域内核 | `stock-analysis-skill` | 行情核验、技术计算、评分、ETF 量化和组合分析 |

## 实际调用链

### 对话主链路（Route 显式执行）

```
stockwise-frontend:8082 → /api/ → stockwise-backend:8081
    → ChatController → AgentOrchestrator
    → Guardrail (输入护栏)
    → RequestRouter (规则优先路由 + 本地模型兜底)
    → RouteDecision (不可变路由决策)
    → RouteExecutionPolicyRegistry (读取允许的 Command/WebSearch/模型等级)
    → ExplicitAnalysisExecutor (Route switch 分发)
        ├─ GENERAL_CHAT / KNOWLEDGE_QA / EXTERNAL_RESEARCH → LocalAnswerClient
        ├─ MARKET_FACT → MarketFactResponder (固定模板)
        ├─ STOCK/PORTFOLIO/QUANT/MARKET_CAUSAL → BoundedReactLoop
        │       → stock-wrapper → stock-analysis-skill → 契约校验
        │       → PaidModelGate.evaluate() → PaidAnalysisClient (门禁放行)
        └─ NEED_CLARIFICATION → 固定追问文本
    → ReAct 审计 (路由决策/工具执行/门禁/模型调用/终止原因)
    → SSE stream (token/agent_run/ask/done)
    → 暂停点 (awaiting_resolution → awaiting_confirm)
    → 知识闭环 (本地模型抽取 → 用户确认 → 去重 → PgVector 入库)
```

### 旧固定报告链（默认关闭）

```
stock-agent.html → StockAgentController → StockAnalysisGateway → stock-wrapper
    → stock-analysis-skill → ReportAssembler → DeepSeek 解释 → SSE/JSON
```

这条链只保留迁移兼容代码，`stockwise.legacy-stock-agent.enabled=false` 时不会注册 Controller；`stock-agent.html` 和 Demo 页面自动跳转到 `stockwise-chat.html`。正式业务只能进入 `ChatController → AgentOrchestrator`。

## 架构优点

1. **Route 是权限真源**：Java 通过 `RouteExecutionPolicyRegistry` 代码层硬编码每种 Route 允许的 Command、WebSearch 权限和模型等级，Prompt 和模型不得扩大。
2. **付费硬门禁**：`PaidModelGate` 对 Skill Observation（成功/契约/命令/标的/时效）和外部证据做 8 条件校验，全部通过才发放 `PaidModelPermit`；`DeepSeekClient` 为包内实现，业务层只能通过 `PaidAnalysisClient` 调用。
3. **有界 ReAct 循环**：`BoundedReactLoop` 统一限制最大轮数、总截止时间、单工具超时、工具预算和重复指纹；每轮 Decision 和终止原因进入 Agent Run 审计。
4. **记忆四类分流**：`MemoryRouter` 统一工作（Redis CAS）、情景（PG 归档/反馈）、语义（pgvector）、业务（持仓/资金配置）入口，会话状态版本化保存。
5. **搜索服务独立**：`web-search-wrapper` 提供逐 Agent 鉴权、限流、缓存、熔断和 SearXNG 结果标准化；`LocalSearchPlanner` 过滤隐私信息后再生成搜索任务。
6. **知识闭环完整**：暂停点 B→用户确认→暂停点 C→本地模型抽取→校验去重→PgVector 入库，全链路无隐藏付费调用。

## 已解决的问题（2026-07-29 前）

| 问题 | 状态 |
|------|------|
| DeepSeek 自主工具调用不可控 | 已由 Route 显式执行替代 |
| 闲聊/知识问答也在烧付费 Token | 已路由到本地模型或固定模板 |
| 知识抽取存在隐藏付费调用 | 已改用本地 qwen3:1.5b |
| 持仓分析用默认 portfolio.json | 已改为数据库真实持仓 `loadRequiredPortfolio` |
| ReAct 无审计可观测性 | 已实现 Agent Run/Step/ToolExecution 持久化与回放 |
| Skill 权限仅靠 Prompt 约束 | 已由 `RouteExecutionPolicyRegistry` 代码层硬控 |
| 会话并发覆盖 | 已通过 Redis Lua CAS + SESSION_BUSY 检测 |
| 对话消息进入URL日志 | 已改为 POST JSON + fetch ReadableStream |
| 浏览器自行指定 userId | 当前单用户模式改为服务端 `stockwise.single-user.id` |
| 输出护栏事后告警 | 已改为完整句子发送前检查，违规片段不下发 |
| SSE与工具线程无界增长 | 已拆为可配置的有界Agent和ReAct线程池 |
| 两套付费分析入口 | 旧 `StockAgentController` 默认不注册，页面统一进入主编排器 |

## 仍需收敛的问题（P1/P2）

1. 云端 Skill 与 WebSearch Gateway 已通过公网 IP 和真实 Token 验收；当前临时使用明文 3001/3002 端口，必须限制来源 IP，并在 HTTPS 入口恢复后关闭。
2. 单用户ID已由服务端提供，但公网部署仍需由Nginx、VPN或后续认证模块限制访问者。
3. RAG已具备相似度门槛和上下文证据注入，但全文召回、RRF融合、rerank和Embedding版本化尚未实现。
4. 云端 PostgreSQL、Redis、MySQL、Ollama 与 Wrapper 已运行，但 Java Backend 尚未在同一服务器完成正式 SSE 聊天入口验收。
5. 缺少Flyway/Liquibase数据库迁移工具，表结构变更靠手工SQL。
6. `knowledge_chunks`仍为单表，`public_knowledge`/`private_knowledge`双表分离属roadmap。

## 建议实施顺序

1. 使用 Linux host 网络部署 Java Backend，完成正式 SSE 聊天入口、记忆、RAG 与云端 Wrapper 联调
2. 引入数据库迁移工具并固定部署基线
3. 全文召回、融合重排和Embedding版本化
4. 单用户公网访问控制或正式认证边界
5. 双表分离、游客模式和更完整前端审计展示
