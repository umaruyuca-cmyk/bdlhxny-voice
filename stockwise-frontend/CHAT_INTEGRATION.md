# 对话页（chat.html）· 后端对接文档

> 适用页面：`public/chat.html` + `public/assets/chat-theme.css` + `public/assets/chat.js`（单助手对话页，2026-08 新版）。
> 旧版双 Agent 工作站（workspace.html）的对接说明见 `API_INTEGRATION.md`，二者并存期间互不影响。
> 本文档以后端（LangChain agent 服务）要实现/对齐的契约为目标整理，前端行为均以 `chat.js` 实际代码为准。

---

## 1. 页面与运行方式

| 项 | 值 |
| --- | --- |
| 页面地址（联调） | `http://127.0.0.1:8082/chat.html` |
| 演示模式 | `http://127.0.0.1:8082/chat.html?mock=1`（不依赖后端，内置模拟事件流与演示数据） |
| 静态服务 | `node dev-server.js`，默认端口 `8082`（`PORT` 可覆盖） |
| API 代理 | 所有 `/api/*` 由 dev-server 透传到后端 `127.0.0.1:8080`（`STOCKWISE_BACKEND_URL` 可覆盖）；生产由 nginx 同规则代理 |
| 前端构建 | 无构建，原生 HTML/CSS/JS，直接静态部署 |

前端只请求**同源相对路径** `/api/v1/*`，不感知后端真实地址。

---

## 2. API 一览

| # | 方法 | 路径 | 用途 | 必需性 |
| --- | --- | --- | --- | --- |
| 1 | POST | `/api/v1/chat/stream` | 流式问答（SSE） | **必需** |
| 2 | GET | `/api/v1/conversations?mode=general&limit=30` | 会话目录（侧边栏列表） | 可选（失败静默降级为纯本地列表） |
| 3 | GET | `/api/v1/conversations/{sessionId}` | 会话消息快照（切换/刷新恢复） | 可选（同上） |
| 4 | GET | `/api/v1/conversations/{sessionId}/messages?before={cursor}&limit=20` | 更早历史分页（上滑加载） | **预留，未实现**（见 §6.3） |

> 旧版的 `agent-runs`、`skill-results`、`instrument`、`ask(NEED_INSTRUMENT)` 等能力，新页面**不调用**。mode 字段当前固定为 `general`。

---

## 3. 流式问答接口（必需）

### 3.1 请求

```
POST /api/v1/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

```json
{
  "sessionId": "s_xxx（客户端生成的临时 ID；已有服务端会话则传服务端 ID）",
  "mode": "general",
  "message": "用户输入的完整问题",
  "instrument": null
}
```

| 字段 | 说明 |
| --- | --- |
| `sessionId` | 新会话是客户端临时 ID（`s_` 前缀）。后端应在事件流中通过 `agent_run.sessionId` 或 `done.sessionId` 下发正式 ID，前端收到后自动替换本地临时 ID 并以正式 ID 续聊 |
| `mode` | 固定 `"general"`（单助手，路由决策全部交给后端） |
| `instrument` | 固定 `null`（前端已无标的选择 UI；如后端需要标的上下文，应通过 `clarification` 事件向用户索取） |

### 3.2 SSE 帧格式

每帧一个 JSON，以 `data: ` 前缀推送，空行分隔：

```
data: {"type":"status","step":"classifying"}

data: {"type":"token","content":"科创芯片ETF"}

data: {"type":"done","status":"COMPLETED","sessionId":"c9f1..."}
```

### 3.3 事件类型契约（前端实际消费）

| type | 字段 | 前端行为 | 必需性 |
| --- | --- | --- | --- |
| `status` | `step`（必需）, `skill`（可选） | 在 AI 消息上方显示阶段小字（流光动画）：`"{阶段文案} · {skill}…"`；首个 token 到达后自动消失 | 推荐 |
| `token` | `content` | 增量追加到回答正文，带流式光标 | **必需** |
| `agent_run` | `sessionId`, `runId`, `route` | 仅消费 `sessionId`：替换本地临时会话 ID | 推荐 |
| `clarification` | `prompt`, `options[]` | 渲染「需要确认」卡片：prompt 为说明文字，options 渲染为按钮；点击按钮把 `options[i].message` 作为新提问自动发送 | 可选 |
| `done` | `status`, `sessionId` | 收尾：停止流式光标、把整段回答存入会话历史。`status=REFUSED` 且回答为空时显示「请求已被护栏拦截：{reason}」 | **必需** |
| `error` | `message` | 红字显示错误并中断当前流 | 推荐 |

`clarification.options[]` 结构：

```json
{
  "type": "clarification",
  "prompt": "选择一个方向后继续分析。",
  "options": [
    { "label": "短线择时", "message": "从短线择时角度分析 588200" },
    { "label": "中长期配置", "message": "从中长期配置角度分析 588200" }
  ]
}
```

### 3.4 `status.step` 取值与前端文案映射

后端可发下列任意 step，未识别的 step 会被忽略（不显示）：

| step | 前端文案 | step | 前端文案 |
| --- | --- | --- | --- |
| `classifying` | 理解你的问题 | `stock_validating` | 校验分析标的 |
| `direct_chat` | 组织回答 | `skill_executing` | 执行深度分析 |
| `react_planning` | 规划分析步骤 | `route_executing` | 执行深度分析 |
| `searching_web` | 联网检索资料 | `searching_vector` | 检索知识库 |
| `reading_sources` | 整理检索来源 | `retrieval_result` | 整理检索结果 |

### 3.5 时序约束

1. `status` 事件可随时发、可多次发（阶段推进时发一次即可，前端只展示最新一条）。
2. `token` 到达即隐藏状态小字；首个 `token` 前前端显示三点等待动画。
3. 每次问答必须以 `done` 或 `error` 结束——前端收到后即停止读取流；**缺失会导致回答不存入会话历史**。
4. `done.sessionId` 是前端替换临时 ID 的最后机会（`agent_run.sessionId` 亦可，二者任一即可）。

---

## 4. 会话接口（可选但建议实现）

### 4.1 会话目录

```
GET /api/v1/conversations?mode=general&limit=30
```

响应：JSON 数组，按更新时间倒序更佳（前端会自行排序）：

```json
[
  {
    "sessionId": "c9f1a2...",
    "title": "科创芯片ETF 还能拿吗",
    "messageCount": 6,
    "updatedAt": "2026-08-09T12:00:00Z"
  }
]
```

- `updatedAt` 需可被 `Date.parse()` 解析，用于侧边栏「今天/昨天/7 天内/30 天内/更早」分组。
- 前端行为：本地 localStorage 列表与远端合并（远端为主，本地未同步的新会话保留）；接口失败/不可用时不报错，纯本地运行。

### 4.2 会话消息快照

```
GET /api/v1/conversations/{sessionId}
```

```json
{
  "session": {
    "sessionId": "c9f1a2...",
    "title": "科创芯片ETF 还能拿吗",
    "messageCount": 6,
    "updatedAt": "2026-08-09T12:00:00Z"
  },
  "messages": [
    { "role": "user", "content": "科创芯片ETF最近跌了这么多，还能拿吗？" },
    { "role": "assistant", "content": "短期回调主要受……" }
  ]
}
```

- 前端只读取 `session.title` 与 `messages[].role/content`；`role` 非 `user` 的一律按 assistant 渲染。
- 该接口当前返回**全量**或**最新一段**消息均可；若实现 §6.3 的分页，此处返回最新一页即可。

---

## 5. 前端本地行为约定（后端无需关心，列出以便联调排查）

| 项 | 值 |
| --- | --- |
| 真实模式存储 | localStorage `grid.chat.v1`（会话列表 + 消息） |
| 演示模式存储 | localStorage `grid.chat.mock.v2` + 版本键 `grid.chat.mock.ver`（当前版本 3，改 mock 数据递增） |
| 临时会话 ID | `s_{timestamp36}{random}`，收到服务端 `sessionId` 后原地替换 |
| 会话标题 | 首条用户消息前 24 字；远端会话以 `session.title` 为准 |
| 单会话保留上限 | 30 条会话 |
| 回答落库时机 | 收到 `done` 时，把本次流式拼接的完整文本作为一条 assistant 消息写入 |

---

## 6. 后端（LangChain agent）对接清单

### 6.1 必须实现

- [ ] `POST /api/v1/chat/stream`：SSE 流，至少发 `token` × N + 收尾 `done`（含 `status`、`sessionId`）。
- [ ] 会话持久化：以 `sessionId` 聚合消息；`title` 可用首条用户问题生成。
- [ ] 幂等/去重：同一 `sessionId` 多轮问答消息追加存储。

### 6.2 建议实现

- [ ] `status` 阶段事件：按 §3.4 的 step 值上报 LangChain 各环节（路由/检索/工具/生成），前端会显示成流光状态文字。
- [ ] `clarification`：需要用户补充信息（如具体标的、分析口径）时发此事件，比纯文本追问体验好。
- [ ] `GET /api/v1/conversations` 两个接口：保证刷新/换设备后会话可恢复。

### 6.3 预留：历史消息分页（上滑加载）

前端已完整实现「滚动到顶部 → 骨架条动画 → 前插更早消息 → 视口不跳动」，数据源当前是本地 `session.earlierBatches`。后端就绪后计划改为：

```
GET /api/v1/conversations/{sessionId}/messages?before={最早一条消息的游标}&limit=20
```

返回该游标之前的一页消息。前端触发与渲染逻辑无需改动，只换数据来源。

---

## 7. 联调步骤

1. 启动后端服务（LangChain agent），确认 `POST /api/v1/chat/stream` 可用。
2. `cd stockwise-frontend && node dev-server.js`（默认 8082）。
3. 打开 `http://127.0.0.1:8082/chat.html?mock=1` 先确认前端交互基线（状态动画/流式/多轮/上滑加载/提问目录均为模拟数据）。
4. 打开 `http://127.0.0.1:8082/chat.html` 走真实链路：发一条问题，观察状态小字 → 流式输出 → 落库；刷新页面确认会话恢复。
5. 验证澄清流程：构造一个需要补充信息的提问，确认 `clarification` 卡片渲染与选项回发。
