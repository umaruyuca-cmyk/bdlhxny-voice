# StockWise Agent：ReAct、Skill 与记忆系统优化方案

> **状态：已实现并于 2026-07-30 增强长期情景记忆。** 本文档保留为设计记录，实际实现方案见 `docs/00-PRD-v3.md`、`docs/architecture-analysis.md` 和 `proposals/langchain4j-memory-optimization.md`。
>
> 原方案建议将隐式 `streamChatWithTools()` 替换为显式 ReAct 状态机、MemoryRouter 四类记忆分流、以及 Route/Intent/Skill 三层责任分离 —— 这些已由以下组件实现：
> - `ExplicitAnalysisExecutor` + `BoundedReactLoop`：显式 Route 分发与有界工具执行
> - `MemoryRouter` + `SessionStateService (Lua CAS)`：四类记忆统一入口与会话并发控制
> - `RequestRouter` + `RouteExecutionPolicyRegistry`：规则优先路由与代码层权限白名单
> - `PaidModelGate` + `PaidAnalysisClient`：付费模型唯一入口与 8 条件硬门禁
>
> 实现细节以当前 PRD v3.3 和代码基线为准。

## 核心判断（已解决）

原问题：`AgentOrchestrator` 仍然是"流程外壳"，真正的工具循环隐藏在 Spring AI 的 `streamChatWithTools()` 内部，缺少生产级 Agent 需要的逐步控制、可观测性、预算约束和恢复能力。

当前已收敛为：

`请求 → 路由(Rule优先+LLM兜底) → RouteDecision → BoundedReactLoop(有界工具执行) → PaidModelGate(付费硬门禁) → 模型回答 → 记忆沉淀`

## 原方案建议（已实现）

1. **显式 ReAct 状态机** → `ExplicitAnalysisExecutor` switch 分发 9 种 Route + `BoundedReactLoop` 统一控制轮数/超时/指纹
2. **Skill Manifest (YAML)** → `RouteExecutionPolicyRegistry` + `SkillDefinition` record 代码层硬编码，不可绕过
3. **三层记忆优化** → `MemoryRouter` 统一入口，Redis CAS 会话状态 + PostgreSQL 完整情景归档 + LangChain4j/PgVector 会话摘要召回 + pgvector 确认知识检索
4. **HybridRetrievalPipeline** → 单阶段 RAG 已落地，全文/融合/rerank 属 roadmap
5. **AgentRun 持久化** → `agent_runs/agent_steps/tool_executions` 三表审计，支持 ReAct 逐步回放
6. **本地模型知识抽取** → `KnowledgeExtractor` 使用 qwen3:1.5b，无隐藏付费调用
