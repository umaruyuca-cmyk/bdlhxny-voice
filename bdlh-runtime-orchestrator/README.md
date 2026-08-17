# BDLH Agent Runtime Analysis

BDLH Agent Runtime 的 Python 分析流程服务（LangGraph + Mem0 主版本）。

当前实现完成 Phase 0 / 1 / 2 / 4 的可运行闭环：动态 `WorkflowPlan` 调度、
Root / Query / Market Data Graph、有界 ReAct 执行矩阵、Mem0 记忆层（首尾读写）、
ContextBuilder 七块上下文、MCP 双传输接入（SSE + Streamable HTTP）、
确定性分析引擎（技术指标/风险/组合影响/回测）、Checkpointer 工厂、JWT 隔离的聊天 SSE API。

M7 另注册了 `plugin_probe` 实验性第二 Domain，用于验证既有
`DomainDescriptor / SkillManifest / Dispatcher / DomainBudget / Observation / Guardrail`
可被新插件直接复用。该探针未加入用户 Cognitive 白名单，不是产品功能入口。

## 架构分层

```text
api/                  FastAPI + SSE 事件流（api_prefix 由 Settings 提供）
runtimes/langgraph/   主版本编排（graphs/agents/nodes/context）
memory/               Mem0 记忆层（base 抽象 + mem0 实现 + NoOp 降级）
integrations/mcp/     MCP 接入（SSE + Streamable HTTP 双传输，实测路由）
tools/                ToolRegistry + 分析能力工具 + Java 数据适配器
observations/         Observation 标准化（含服务端吞错识别）
domain/               确定性计算（零框架依赖）：指标/风险/回测/策略/交易日历
```

对话入口统一为 Root Graph：知识问答走一次直接 LLM 调用（非 ReAct、无 Tool），
复杂市场研究才进入有界 ReAct 子图；标的解析、计算和校验保持确定性节点。

## 当前边界

- 已实现：流程状态、Checkpointer 工厂（memory/postgres/redis）、`interrupt()/resume`、
  SSE API、MCP 实测路由（xueqiu/sina 异构备份）、fallback 降级、服务端吞错识别、
  Mem0 记忆降级、Java 数据适配（生产禁 mock）、交易日历、确定性分析引擎；
- 未实现：Letta 对比 Runtime（主版本稳定后启动）、真实下单/撤单、Node Skill 独立部署评估；
- Mock 数据只用于流程测试（带 is_mock 标记），不能用于任何真实市场结论；
- 生产环境：需配置 `DEEPSEEK_API_KEY`、`POSTGRES_DSN`/`REDIS_URL`、两个 MCP endpoint。

## 本地运行

```powershell
uv sync --extra dev
uv run uvicorn bdlh_runtime.main:app --reload
```

前端开发服务器默认把聊天请求代理到 `127.0.0.1:8000`。生产容器监听
`127.0.0.1:8090`，并使用异步 PostgreSQL Checkpointer 与 PostgreSQL 会话目录。

## 测试

```powershell
uv run --extra dev python -m pytest tests -q
```

覆盖：Workflow 调度、ReAct 回归（Fake Gateway）、MCP 解析/fallback、记忆降级、
分析引擎可复现性、回测无未来函数、交易日历、API 前缀。

## M6 价格观察任务

M6 只启用一种持续任务：用户确认的价格阈值观察。创建请求必须携带 JWT、
`Idempotency-Key` 和 `confirmed=true`，Scheduler 每次唤醒都会重新进入 Cognitive +
Finance 获取当前市场事实；`PARTIAL/LIMITED` 数据不会触发通知。

生产启用前先执行 `db/migrations/20260812_financial_tasks.sql`，然后在目标 Worker
实例配置 `BDLH_FINANCIAL_TASK_WORKER_ENABLED=true`。任务 API 为
`/api/v1/financial-tasks*`，已发送站内通知查询为 `/api/v1/notifications`。
