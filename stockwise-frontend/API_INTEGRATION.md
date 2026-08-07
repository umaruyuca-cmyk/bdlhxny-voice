# StockWise 前端 · 后端对接说明

> 本文档说明前端页面如何与后端对接：页面地址、路由、API 契约与 SSE 事件流。
> 前端通过 dev-server 反向代理把所有 `/api/*` 请求转发到后端，前端页面本身不关心后端地址。

---

## 1. 页面地址（联调用）

前端 dev-server 默认端口 `8082`，也可用 `PORT` 环境变量覆盖。下表使用默认端口。

| 页面 | 地址 | 说明 |
| --- | --- | --- |
| 首页 | `http://127.0.0.1:8082/` | 首屏输入框 → 跳转工作站 |
| 智能问答 | `http://127.0.0.1:8082/agent?name=general` | 通用 Agent |
| 股市分析 | `http://127.0.0.1:8082/agent?name=stock` | 市场与标的研究 Agent；板块问题可直接提问，单标的决策才需选择标的 |
| 文档中心 | `http://127.0.0.1:8082/docs` | 用户与开发者文档索引 |
| Skill 接入规范 | `http://127.0.0.1:8082/docs/skill` | 通用 Skill 接入文档 |
| Agent 与路由 | `http://127.0.0.1:8082/docs/agents` | 领域分析说明 |
| Skill 生态 | `http://127.0.0.1:8082/skill-dashboard.html` | 多 Skill 服务目录 |
| API 联调页（开发工具） | `http://127.0.0.1:8082/api-console.html` | 仅开发人员测试 SSE 与运行记录 |

### 页面联动参数
- `?name=general|stock` —— 选择 Agent（workspace.html）
- `?q=问题内容` —— 自动带入并发送问题（首页输入框跳转时带上）
- `?mode=general|stock` —— 仅供历史兼容页面使用，正式入口统一使用 `?name=general|stock`

首页 → 工作站的跳转逻辑：输入含 6 位数字判定为 `stock`，否则 `general`，并携带 `q` 参数。
进入 Stock Agent 后，用户可直接询问市场或板块问题；只有涉及单只股票、ETF 或基金的方向判断，后端才会通过 `ask` 事件要求补充标的。

---

## 2. 前端 → 后端 API 契约

前端调用以下 3 组接口（全部经 `/api/*` 代理转发，方法、路径、请求体原样透传）。

### 2.1 流式对话（SSE）

```
POST /api/v1/chat/stream
Accept: text/event-stream
Content-Type: application/json
```

请求体：

```json
{
  "sessionId": "string (客户端临时 uuid 或服务端返回的 canonical sessionId)",
  "mode": "general | stock",
  "message": "用户问题",
  "instrument": {
    "symbol": "588200",
    "assetType": "ETF"
  }
}
```

> `instrument` 仅 `stock` 模式且用户已选择标的存在；`general` 模式为 `null`。

响应为 SSE 流，每帧 `data: {json}`，事件类型见下表。

### 2.2 会话目录与消息恢复

```
GET /api/v1/conversations?mode=general|stock&limit=20
GET /api/v1/conversations/{sessionId}
Accept: application/json
```

会话目录由后端持久化，前端 `localStorage` 只作为离线缓存。详情接口返回会话元数据和最新完整消息快照，用于刷新页面或切换左侧会话。

### 2.3 运行追踪与 Skill 结果

```
GET /api/v1/agent-runs?limit=20          // 最近运行列表
GET /api/v1/agent-runs/{runId}          // 单条运行详情
GET /api/v1/agent-runs/{runId}/skill-results // 本轮可展示的结构化 Skill 结果
Accept: application/json
```

> 说明：`POST /api/v1/chat/guest-analysis-quota` 已随游客配额功能一并移除，前端与文档不再调用或宣传该接口。若未来恢复游客次数限制，必须同时实现后端身份识别、配额存储、校验、错误响应、前端展示和测试，不能只改文档或前端。

---

## 3. SSE 事件流契约（/api/v1/chat/stream）

每帧 JSON 通过 `data:` 前缀推送，事件由 `type` 字段区分。前端按下列顺序消费：

| type | 关键字段 | 含义 / 前端行为 |
| --- | --- | --- |
| `status` | `step`, `skill?` | 阶段状态。当前使用 `classifying` / `direct_chat` / `react_planning` / `searching_web` / `reading_sources` / `stock_validating` / `skill_executing`，驱动状态条 |
| `token` | `content` | 增量文本 token，追加到回答气泡 |
| `ask` | `prompt`, `reason?`, `options?` | 主动提问（用于需要澄清/选标的），展示为问题卡片，`options` 为可选按钮 |
| `clarification` | `prompt`, `reason?`, `options?` | 澄清说明 |
| `agent_run` | `runId`, `sessionId`, `status?`, `route?`, `skill?` | 上报一次运行追踪的 ID 与后端正式会话 ID，填充「运行追踪」面板并同步 URL |
| `done` | 见下表 | 对话结束，携带本轮运行与 Skill 结果的完整元数据 |

### 3.1 `done` 事件字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | `COMPLETED` / `NEED_CLARIFICATION` / `REFUSED` / `RESOLVED` / `CLOSED` |
| `runId` | string | 本轮运行 ID |
| `sessionId` | string | 后端正式会话 ID；前端首次发送的临时 ID 会在收到该字段后替换 |
| `skill` | string | 命中的 Skill 名 |
| `route` | string | 业务路由（如 `STOCK_ANALYSIS`） |
| `internalRoute` | string | 内部路由（如 `QUANT_DECISION`） |
| `mode` | string | 会话模式（`general` / `stock` / `legacy`） |
| `modelTier` | string | 模型层级（`LOCAL` / `PAID`） |
| `modelProvider` / `modelName` | string | 实际回答来源的模型供应商与名称 |
| `gateReason` | string | 付费门禁触发原因（如为空表示未拦截） |
| `reactTerminationReason` | string | ReAct 终止原因 |
| `reactRounds` / `reactToolCalls` | number | ReAct 轮数与工具调用次数 |
| `skillResultAvailable` | boolean | 是否有本轮可展示的结构化 Skill 结果 |
| `skillResult` | object | 本轮 StockSkill 结构化结果（行情/指标/热度等），游客可直接打开看板，无需请求受保护的运行审计接口 |

> `modelTier` 的 `LOCAL` 仅是后端策略层级，不代表 Ollama；回答的真实来源以 `modelProvider` / `modelName` 为准。

### 完整事件序列示例

```json
data: {"type":"status","step":"classifying"}

data: {"type":"status","step":"searching_web"}

data: {"type":"agent_run","runId":"3f2b...","route":"react_planning"}

data: {"type":"token","content":"根据最近"}

data: {"type":"token","content":"的板块数据"}

data: {"type":"status","step":"writing"}

data: {"type":"done","message":"..."}
```

---

## 4. 运行追踪数据形态

`GET /api/v1/agent-runs/{runId}` 响应的核心结构（前端渲染依赖）：

```json
{
  "run": {
    "runId": "3f2b...",
    "mode": "stock",
    "question": "今天哪些行业板块最强？",
    "status": "COMPLETED",
    "createdAt": "2026-08-02T12:00:00Z"
  },
  "steps": [
    {
      "order": 1,
      "type": "TOOL_CALL",
      "name": "sector_heat",
      "summary": "查询行业板块热度",
      "status": "OK",
      "durationMs": 820
    }
  ],
  "toolExecutions": [
    {
      "toolName": "sector",
      "status": "success",
      "observationJson": { "schemaVersion": "1.1", "command": "sector", "data": {} }
    }
  ]
}
```

### 4.1 结构化 Skill 结果

`GET /api/v1/agent-runs/{runId}/skill-results` 只返回可被界面展示的 `stock`、`sector`、`quant`、`portfolio` 结果，不返回完整审计信息或模型隐藏推理。

```json
{
  "runId": "3f2b...",
  "items": [
    {
      "command": "sector",
      "durationMs": 820,
      "observation": { "schemaVersion": "1.1", "command": "sector", "data": {} }
    }
  ]
}
```

前端在 SSE `done.skillResultAvailable=true` 后显示按钮；用户点击后再请求该接口并按 `command` 渲染图表、判断依据和数据质量。这样回答正文保持简洁，数据看板也能单独回看。

---

## 5. 联调步骤

1. 启动后端（默认 `127.0.0.1:8080`），确认健康检查通过。
2. 启动前端 dev-server：`node dev-server.js`（默认端口 8082）。
3. 打开 `http://127.0.0.1:8082/api-console.html` 逐项测试 SSE 与运行记录。
4. 打开 `http://127.0.0.1:8082/agent?name=stock`，发送问题，观察 SSE 是否推进、运行追踪面板是否刷新。
5. 后端不可用时前端会走本地模拟（`simulateReply`），不影响演示，联调时以真实响应为准。
