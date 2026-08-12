# 对话页（chat.html）· 后端对接文档

> 适用页面：`public/chat.html` + `public/assets/chat-theme.css` + `public/assets/chat.js`（单助手对话页，2026-08 新版）。
> 旧版双 Agent 工作站（workspace.html）的对接说明见 `API_INTEGRATION.md`，当前仅保留 `/workspace` 兼容入口；默认 `/agent` 已切换到新版页面。
> 本文档以 Python LangGraph 分析系统要实现/对齐的契约为目标整理，前端行为均以 `chat.js` 实际代码为准。页面不是某个 Agent 的专属 UI；Root Graph 负责系统流程，只有部分节点使用 Agent 或直接模型调用。

---

## 1. 页面与运行方式

| 项 | 值 |
| --- | --- |
| 页面地址（联调） | `http://127.0.0.1:8082/chat.html` |
| 演示模式 | `http://127.0.0.1:8082/chat.html?mock=1`（不依赖后端，内置模拟事件流与演示数据） |
| 静态服务 | `node dev-server.js`，默认端口 `8082`（`PORT` 可覆盖） |
| API 代理 | 认证/用户 API → Java `127.0.0.1:8081`（`STOCKWISE_BACKEND_URL`）；聊天/会话 → Python `127.0.0.1:8000`（`STOCKWISE_ANALYSIS_URL`）。生产 Python 使用 `127.0.0.1:8090` |
| 前端构建 | 无构建，原生 HTML/CSS/JS，直接静态部署 |

前端只请求**同源相对路径** `/api/v1/*`，不感知后端真实地址。

---

## 2. API 一览

| # | 方法 | 路径 | 用途 | 必需性 |
| --- | --- | --- | --- | --- |
| 1 | POST | `/api/v1/chat/stream` | 流式问答（SSE） | **必需** |
| 2 | GET | `/api/v1/conversations?mode=general&limit=30` | 会话目录（侧边栏列表） | 可选（失败静默降级为纯本地列表） |
| 3 | GET | `/api/v1/conversations/{sessionId}` | 会话消息快照（切换/刷新恢复） | 可选（同上） |
| 4 | DELETE | `/api/v1/conversations/{sessionId}` | 删除当前用户的服务端会话 | 已实现 |
| 5 | GET | `/api/v1/conversations/{sessionId}/messages?before={cursor}&limit=20` | 更早历史分页（上滑加载） | **预留，未实现**（见 §6.4） |

真实模式下，上述接口均携带 Java 登录接口签发的 `Authorization: Bearer {JWT}`。Python 只信任 JWT 的 `sub` 作为 `user_id`，请求体不允许自行声明其他用户身份。

> 旧版的 `agent-runs`、`skill-results`、`instrument`、`ask(NEED_INSTRUMENT)` 等能力，新页面**不调用**。mode 字段当前固定为 `general`。

---

## 3. 流式问答接口（必需）

### 3.1 请求

```
POST /api/v1/chat/stream
Content-Type: application/json
Accept: text/event-stream
Authorization: Bearer {JWT}
```

```json
{
  "sessionId": "s_xxx（客户端生成的临时 ID；已有服务端会话则传服务端 ID）",
  "mode": "general",
  "message": "用户输入的完整问题",
  "instrument": null,
  "regenerate": false
}
```

| 字段 | 说明 |
| --- | --- |
| `sessionId` | 新会话是客户端临时 ID（`s_` 前缀）。后端应在事件流中通过 `agent_run.sessionId` 或 `done.sessionId` 下发正式 ID，前端收到后自动替换本地临时 ID 并以正式 ID 续聊 |
| `mode` | 固定 `"general"`（单助手，路由决策全部交给后端） |
| `instrument` | 固定 `null`（前端已无标的选择 UI；如后端需要标的上下文，应通过 `clarification` 事件向用户索取） |
| `regenerate` | 默认 `false`；重新生成时为 `true`，服务端替换上一条 assistant 快照，不重复追加用户问题 |

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
| `clarification` | `prompt`, `options[]` | 渲染「需要确认」卡片；有选项时点击回发，无选项时提示用户直接在输入框补充。下一条消息恢复同一 Graph run/checkpoint | 可选 |
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
| 真实模式存储 | localStorage `grid.chat.v1.{userId}`（会话列表 + 消息，按登录用户隔离） |
| 演示模式存储 | localStorage `grid.chat.mock.v2` + 版本键 `grid.chat.mock.ver`（当前版本 3，改 mock 数据递增） |
| 临时会话 ID | `s_{timestamp36}{random}`，收到服务端 `sessionId` 后原地替换 |
| 会话标题 | 首条用户消息前 24 字；远端会话以 `session.title` 为准 |
| 单会话保留上限 | 30 条会话 |
| 回答落库时机 | 收到 `done` 时，把本次流式拼接的完整文本作为一条 assistant 消息写入 |

---

## 6. 后端（Python LangGraph 系统）对接清单

### 6.1 必须实现

- [x] `POST /api/v1/chat/stream`：SSE 流，由 Root Graph 执行并以 `done/error` 收尾。
- [x] JWT 用户隔离：公开 `sessionId` 相同也不能跨用户读取、恢复或删除。
- [x] 会话持久化：开发环境使用内存实现；生产环境强制 PostgreSQL。
- [x] 多轮与恢复：普通续聊创建新 run；澄清续答从待恢复 checkpoint 继续。
- [x] 重新生成去重：替换最后一条 assistant 快照，不重复用户消息。

### 6.2 建议实现

- [x] `status` 阶段事件：按顶层/子图节点更新映射为路由、规划、工具和生成阶段。
- [x] `clarification`：Graph `interrupt()` 暂停，用户下一条消息通过 `Command(resume=...)` 恢复。
- [x] 会话列表、详情和删除接口：刷新与换设备后可恢复，删除失败不会先清空本地记录。

### 6.3 节点执行模式边界

| 场景/节点 | 执行模式 | 是否 ReAct | Tool 权限 |
| --- | --- | --- | --- |
| `query_graph` | StateGraph 子图；意图理解可使用结构化 LLM，路由/缺失条件为确定性代码 | 否 | 无 |
| `direct_response` | 一次受控 LLM 调用；模型不可用时确定性降级 | 否 | 无 |
| `market_data_graph` 复杂研究 | 有预算、最大步数和结束条件的研究 Agent | 是 | 仅本轮候选能力白名单 |
| 标的解析、组合读取、分析计算、校验 | 普通服务/确定性节点 | 否 | 仅节点显式绑定能力 |
| `compose_response` | 对已验证 `AnalysisResult` 的一次 LLM 总结 | 否 | 无 |

前端只展示阶段，不决定上述模式。Agent 不能决定 Root Graph 的终止条件，也不能绕过节点白名单直接调用任意 MCP tool。

### 6.4 预留：历史消息分页（上滑加载）

前端已完整实现「滚动到顶部 → 骨架条动画 → 前插更早消息 → 视口不跳动」，数据源当前是本地 `session.earlierBatches`。后端就绪后计划改为：

```
GET /api/v1/conversations/{sessionId}/messages?before={最早一条消息的游标}&limit=20
```

返回该游标之前的一页消息。前端触发与渲染逻辑无需改动，只换数据来源。

---

## 7. 联调步骤

1. 启动 Java 用户服务（本地 8081）和 Python LangGraph 服务（本地 8000），确认登录与聊天接口可用。
2. `cd stockwise-frontend && node dev-server.js`（默认 8082）。
3. 打开 `http://127.0.0.1:8082/chat.html?mock=1` 先确认前端交互基线（状态动画/流式/多轮/上滑加载/提问目录均为模拟数据）。
4. 打开 `http://127.0.0.1:8082/agent` 走真实链路：登录后发一条问题，观察状态小字 → 流式输出 → 落库；刷新页面确认会话恢复。
5. 验证澄清流程：构造一个需要补充信息的提问，确认 `clarification` 卡片渲染与选项回发。
