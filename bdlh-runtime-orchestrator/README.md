# BDLH Agent Runtime Analysis

BDLH Agent Runtime 的 Python 分析流程服务（LangGraph + Mem0 主版本）。

当前实现以 Cognitive Orchestrator 为唯一产品路径（聊天页 + 可选 Skill 插件）：
Domain Dispatcher、Capability Gateway、Observation、Guardrails、Mem0/Remote Memory、
MCP 双传输、确定性分析引擎、Checkpointer 工厂、JWT 隔离的聊天 SSE API。
金融是第一个 Domain Skill 插件，不是默认意图机。

## 架构分层

```text
api/                  FastAPI + SSE 事件流（api_prefix 由 Settings 提供）
runtimes/langgraph/   直接回答模型等支撑组件
memory/               Mem0 记忆层（base 抽象 + mem0 实现 + NoOp 降级）
integrations/mcp/     MCP 接入（SSE + Streamable HTTP 双传输，实测路由）
tools/                Capability 视图 + Java/WebSearch 适配器 + deep_research + 分析能力
observations/         Observation 标准化（含服务端吞错识别）
domain/               确定性计算（零框架依赖）：指标/风险/交易日历/分析引擎
cognitive/            Cognitive Orchestrator（唯一产品编排入口）
domains/finance/      Finance Domain Runtime + Skill Manifest
```

对话入口统一为 Cognitive Orchestrator：快路径 → Understand → GoalAction →
可选金融 Skill 插件；不再装配 Root Graph / 金融默认兜底选择器。

## 当前边界

- 已实现：流程状态、Checkpointer 工厂（memory/postgres/redis）、`interrupt()/resume`、
  SSE API、MCP 实测路由（xueqiu/sina 异构备份）、fallback 降级、服务端吞错识别、
  Mem0 记忆降级、Java 数据适配（生产禁 mock）、交易日历、确定性分析引擎；
- 未实现：Letta 对比 Runtime（主版本稳定后启动）、真实下单/撤单、Node Skill 独立部署评估；
- Mock 数据只用于流程测试（带 is_mock 标记），不能用于任何真实市场结论；
- 运行环境：需配置 `JAVA_API_BASE_URL`、`JAVA_DATA_INTERNAL_TOKEN`、`LLM_API_KEY`（默认 GLM-4.7）和两个 MCP endpoint。

## 本地运行

```powershell
uv sync --extra dev
uv run uvicorn bdlh_runtime.main:app --reload
```

前端开发服务器默认把聊天请求代理到 `127.0.0.1:8090`（与生产编排器端口一致），
并使用异步 PostgreSQL Checkpointer 与 PostgreSQL 会话目录。

## 测试

```powershell
uv run --extra dev python -m pytest tests -q
```

覆盖：Cognitive 编排、MCP 解析/fallback、记忆降级、
分析引擎可复现性、交易日历、API 契约与身份隔离。

## M6 价格观察任务

M6 只启用一种持续任务：用户确认的价格阈值观察。创建请求必须携带 JWT、
`Idempotency-Key` 和 `confirmed=true`，Scheduler 每次唤醒都会重新进入 Cognitive +
Finance 获取当前市场事实；`PARTIAL/LIMITED` 数据不会触发通知。

开发环境全量建库时，按根目录 `db/README.md` 的顺序执行数据库脚本，然后在目标 Worker
实例配置 `BDLH_FINANCIAL_TASK_WORKER_ENABLED=true`。任务 API 为
`/api/v1/financial-tasks*`，已发送站内通知查询为 `/api/v1/notifications`。
