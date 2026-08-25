# Sentinel 前端 · 后端对接

说明页面路由、HTTP API 与 SSE 通道如何接到 Java 数据面与 Python Agent 引擎。浏览器只访问同源 `/api/*`；`dev-server.js` / `nginx.conf` 按路径分发。

产品权威描述见 [`docs/architecture/00-Sentinel产品设计与架构.md`](../docs/architecture/00-Sentinel产品设计与架构.md) §6 / §7。会话通道细节见 [`CHAT_INTEGRATION.md`](CHAT_INTEGRATION.md)。

---

## 1. 页面地址（联调用）

前端默认端口 `8082`（`PORT` 可覆盖）。

| 设计 | 路由 | 实现 | 说明 |
| --- | --- | --- | --- |
| 品牌落地 | `/` | `index.html` | Grid Universe 品牌页；CTA「进入看护」 |
| P1 看护首页 | `/dashboard` | `dashboard.html` | 持仓概览、事件时间线、活跃监视、追问抽屉 |
| P2 会话 / 追问 | `/chat` | **`/agent` → `chat.html`** | 自由问答；追问经 P1 右滑抽屉 iframe 装入同一页 |
| P3 通知中心 | `/notifications` | 未独立成页 | Header 铃铛 + P1 时间线 |
| P4 监视规则 | `/watch-rules` | 入口链接已挂；规则 CRUD 页未交付 | P1 监视条读 `GET /watch-rules`，404 为空态 |
| P5 记忆管理 | `/memory` | 未交付 | — |
| P6 运行回放 | `/runs/{id}` | 引擎有 `GET /api/v1/agent-runs/{id}`；独立回放页未交付 | — |
| 文档 | `/docs` | 已有 | Sentinel 架构 / 双通道 / 工具治理 |
| 开发遗留 | `/skills/` | 保留路由，非产品入口 | 旧 Skill 试用页；调试用 |
| 开发工具 | `/api-console.html` | 已有 | 仅开发人员 |

兼容：`/workspace` → 301 `/agent`。历史 `?mode=` 双 Agent 分流与「插件启停」UI 已退役；`?q=` 仍可自动发送问题；`?name=stock` 仅从 URL 剥离，不再启停 Skill。产品会话请求固定传 `enabledSkillIds: []`（契约字段保留）。

---

## 2. HTTP API（§6.1）

全部经 `/api/*` 代理，方法与路径原样透传。会话身份只来自 JWT。

| 方法 | 路径 | 后端 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/v1/chat/stream` | Python | 会话 SSE（§6.2） |
| GET / DELETE | `/api/v1/conversations[/{id}]` | Python | 会话目录与快照 |
| GET / POST | `/api/v1/agent-runs[/{id}[/pause|/cancel|/resume|/events]]` | Python | 运行快照与 Pause/Cancel |
| GET | `/api/v1/notifications` | Python | 通知列表；`?unread=count` 未读数 |
| GET | `/api/v1/notifications/stream` | Python | 看护通道 SSE（`notification`）；失败则 30s 轮询 |
| POST | `/api/v1/notifications/{id}/followup` | Python | 返回 `session_id` + `event_summary`，打开追问抽屉 |
| GET / POST / PATCH / DELETE | `/api/v1/watch-rules[/{id}]` | Python（目标） | 监视规则；当前未实现时前端按空态 + 区域重试 |
| POST | `/internal/demo/events` | Python（仅 demo 档） | 演示注入，须全程「演示注入」水印（C-4） |
| GET | `/api/v1/ready` · `/ready` | Python | 就绪探针；LLM / 记忆失败映射降级条 |
| GET / POST | `/api/v1/auth/*` | Java | 登录 / 注册 / me |
| GET | `/api/portfolio/positions` | Java | 持仓概览；无行情时今日/浮盈显示「—」 |

---

## 3. SSE 通道

两条流，都用 `fetch` + `getReader()`，不用 `EventSource`（以便带 `Authorization`）。

### 3.1 会话通道

`POST /api/v1/chat/stream`。事件：`agent_run`、`tool.step`、`token`、`response.final`、`done`。完整字段与 ChatResult v2 / ResultBlock 见 `CHAT_INTEGRATION.md`。

`token` 为 LLM `astream` 真流式，禁止定长伪切片。`tool.step` 含 `search_tools`（检索词 + 命中数）。`done.status` ∈ `COMPLETED` | `NEED_CLARIFICATION` | `FAILED`。

### 3.2 看护通道

`GET /api/v1/notifications/stream`。事件：`notification`（时间线 prepend、铃铛 +1；critical 可提示音）。断线指数退避重连，并回退 `GET /notifications` 30s 轮询。

---

## 4. 追问抽屉

1. 时间线「追问」→ `POST /api/v1/notifications/{id}/followup`
2. 响应 `event_summary` 写入抽屉顶部 chip
3. iframe：`/agent?sessionId={session_id}&followup={摘要}&embed=1`
4. 自由会话无 chip；追问会话顶部展示事件上下文

---

## 5. 徽标与演示档（§7.2 / C-4）

`assets/badges.js` 为全局组件：审计码、证据编号 `[n]`、演示注入水印、严重度条。看护首页 Header 在 demo 档常驻「演示数据」横幅。注入事件须在事件卡 / 通知 / 追问上下文可辨识，不得伪装为真实行情。
