# sentinel-engine（Sentinel Agent 引擎）

Sentinel 产品的 Python 引擎（FastAPI）。承担两条驱动通道共用的 Agent 执行能力：

- **看护环**：事件源（价格轮询 / 晨报定时 / 演示注入）→ 唤醒 → 上下文组装 → 结构化事件解读 → 通知；
- **会话通道**：语义快路径分流 → Agent 循环（LLM tool calling）→ SSE 真流式应答。

设计真源：[`docs/architecture/00-Sentinel产品设计与架构.md`](../docs/architecture/00-Sentinel产品设计与架构.md)；
文件归属规则：[`docs/00-仓库文件管理树.md`](../docs/00-仓库文件管理树.md)。

> 本服务正处于按新设计重构的过程中（设计文档 §10 T0–T4）。以下为**目标形态**，
> 与代码现状存在差异时以实施阶段工单收敛，落地前以代码事实为准。

## 架构分层（目标形态）

```text
api/                  FastAPI 入口：SSE、REST、鉴权
watch/                事件源与唤醒调度（T1 新增）
routing/              语义快路径（现 cognitive/semantic_router/）
engine/               统一 Agent 循环（现 cognitive/ 重构而来，T2）
tools/                统一工具目录：本地 pydantic 工具 + MCP ToolCard（T2）
governance/           治理中间件（现 guardrails/ 演化，T2）
context/              上下文组装器（会话态 / 唤醒态）
memory/               L3 记忆客户端（Remote Memory Service）
domain/               确定性计算（零框架依赖）：指标 / 风险 / 交易日历
integrations/mcp/     MCP 接入
observations/         Observation 标准化
runtime/              装配、运行控制、checkpoint、任务调度
prompts/              prompt 资产（独立文件、版本化、eval 门禁）
domains/              【RETIRED】域插件框架，T2 物理删除（统一工具目录取代）
```

核心原则：**模型提议，代码裁决**——意图理解与工具选择由模型完成（快路径 + 原生
tool calling）；只读、权限、预算等不可挽回决策由治理中间件以代码强制。

## 边界

- Mock 数据只用于开发 / 测试（带 `is_mock` 标记），不得用于任何真实市场结论；
- 不具备任何交易执行能力（设计文档 C-1）；
- 适合度输出仅为风险匹配筛查草稿（DRAFT），不出具适当性结论（C-2）；
- 运行依赖：`JAVA_API_BASE_URL`、`JAVA_DATA_INTERNAL_TOKEN`、`LLM_API_KEY`（默认智谱 GLM）、MCP endpoints；依赖缺失经 `/ready` 显性报 degraded，不静默降级。

## 本地运行

```powershell
uv sync --extra dev
uv run uvicorn bdlh_runtime.main:app --reload --host 127.0.0.1 --port 8090
```

## 测试

```powershell
uv run pytest -q
```

覆盖：Agent 循环、语义路由、治理中间件、看护环（事件源 / 幂等 / 唤醒）、记忆降级、
checkpoint 恢复、API 契约与身份隔离、内核纯净度门禁（`tests/architecture/`）。
eval 对照题库见 `tests/eval/`（T2 起）。
