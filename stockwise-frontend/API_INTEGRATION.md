# StockWise 前端 · 后端对接说明

> 本文档说明前端页面如何与后端对接：页面地址、路由、API 契约与 SSE 事件流。
> 前端通过 dev-server 反向代理把所有 `/api/*` 请求转发到后端，前端页面本身不关心后端地址。

---

## 1. 页面地址（联调用）

前端 dev-server 默认端口 `8082`，也可用 `PORT` 环境变量覆盖（本机测试用 `8083`）。

| 页面 | 地址 | 说明 |
| --- | --- | --- |
| 首页 | `http://127.0.0.1:8083/` | 首屏输入框 → 跳转工作站 |
| 智能问答 | `http://127.0.0.1:8083/agent?name=general` | 通用 Agent |
| 股市分析 | `http://127.0.0.1:8083/agent?name=stock` | 市场与标的研究 Agent；板块问题可直接提问，单标的决策才需选择标的 |
| 旧版聊天 | `http://127.0.0.1:8083/stockwise-chat.html?mode=general\|stock` | 兼容页面 |
| 旧版聊天-柔版 | `http://127.0.0.1:8083/stockwise-chat-soft.html?mode=general\|stock` | 兼容页面 |
| API 联调页 | `http://127.0.0.1:8083/api-console.html` | 快速测试各接口 |

### 页面联动参数
- `?name=general|stock` —— 选择 Agent（workspace.html）
- `?q=问题内容` —— 自动带入并发送问题（首页输入框跳转时带上）
- `?mode=general|stock` —— 旧版聊天页的 Agent 选择

首页 → 工作站的跳转逻辑：输入含 6 位数字判定为 `stock`，否则 `general`，并携带 `q` 参数。
进入 Stock Agent 后，用户可直接询问市场或板块问题；只有涉及单只股票、ETF 或基金的方向判断，后端才会通过 `ask` 事件要求补充标的。

---

## 2. 前端 → 后端 API 契约

前端只调用以下 3 组接口（全部经 `/api/*` 代理转发，方法、路径、请求体原样透传）。

### 2.1 流式对话（SSE）

```
POST /api/v1/chat/stream
Accept: text/event-stream
Content-Type: application/json
```

请求体：

```json
{
  "sessionId": "string (uuid)",
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

### 2.2 访客分析额度

```
GET /api/v1/chat/guest-analysis-quota
Accept: application/json
```

响应体（示例）：

```json
{
  "guest": true,
  "applicable": true,
  "used": 3,
  "limit": 5,
  "remaining": 2
}
```

> 前端拿到 `guest:false` 或 `applicable:false` 时隐藏额度角标。

### 2.3 运行追踪

```
GET /api/v1/agent-runs?limit=20          // 最近运行列表
GET /api/v1/agent-runs/{runId}          // 单条运行详情
GET /api/v1/agent-runs/{runId}/skill-results // 本轮可展示的结构化 Skill 结果
Accept: application/json
```

---

## 3. SSE 事件流契约（/api/v1/chat/stream）

每帧 JSON 通过 `data:` 前缀推送，事件由 `type` 字段区分。前端按下列顺序消费：

| type | 关键字段 | 含义 / 前端行为 |
| --- | --- | --- |
| `status` | `step`, `skill?` | 阶段状态。当前使用 `classifying` / `direct_chat` / `react_planning` / `searching_web` / `reading_sources` / `stock_validating` / `skill_executing`，驱动状态条 |
| `token` | `content` | 增量文本 token，追加到回答气泡 |
| `ask` | `prompt`, `reason?`, `options?` | 主动提问（用于需要澄清/选标的），展示为问题卡片，`options` 为可选按钮 |
| `clarification` | `prompt`, `reason?`, `options?` | 澄清说明 |
| `agent_run` | `runId`, `status?`, `route?`, `skill?` | 上报一次运行追踪的 ID 与路由信息，填充「运行追踪」面板 |
| `quota` | `quotaType`, `used?`, `limit?`, `remaining?` | 实时额度更新 |
| `done` | `message?`, `runId?`, `skillResultAvailable?` | 对话结束；`skillResultAvailable=true` 时前端展示“查看本次分析数据”按钮 |

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
2. 启动前端 dev-server：`PORT=8083 node dev-server.js`。
3. 打开 `http://127.0.0.1:8083/api-console.html` 逐项测试 3 组接口。
4. 打开 `http://127.0.0.1:8083/agent?name=stock`，发送问题，观察 SSE 是否推进、运行追踪面板是否刷新。
5. 后端不可用时前端会走本地模拟（`simulateReply`），不影响演示，联调时以真实响应为准。
