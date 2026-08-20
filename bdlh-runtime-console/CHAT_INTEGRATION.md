# 对话页（chat.html）· 后端对接文档

> 适用页面：`public/chat.html` + `public/assets/chat-theme.css` + `public/assets/chat.js`（单助手对话页）。
> 正式入口为 `/agent`；旧 `/workspace` 永久重定向到 `/agent`，双 Agent 工作站页面已删除。
> 后端编排唯一路径为 Python Cognitive Orchestrator（`cognitive_finance`）→ Domain Dispatcher → Finance Runtime。前端行为以 `chat.js` 实际代码为准。

---

## 1. 页面与运行方式

| 项 | 值 |
| --- | --- |
| 页面地址（联调） | `http://127.0.0.1:8082/chat.html` 或 `/agent` |
| 演示模式 | `http://127.0.0.1:8082/chat.html?mock=1`（不依赖后端，内置模拟事件流与演示数据） |
| 静态服务 | `node dev-server.js`，默认端口 `8082`（`PORT` 可覆盖） |
| API 代理 | 认证/用户 API → Java `127.0.0.1:8081`（`BDLH_RUNTIME_BACKEND_URL`）；聊天/会话 → Python `127.0.0.1:8090`（`BDLH_RUNTIME_ANALYSIS_URL`） |
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

真实模式下，上述接口均携带 Java 登录接口签发的 `Authorization: Bearer {JWT}`。Python 只信任 JWT 的 `sub` 作为 `user_id`，请求体不允许自行声明其他用户身份。

> mode 字段当前固定为 `general`（前端兼容字段，不分流编排路径）。

---

## 3. 流式问答接口（必需）

`POST /api/v1/chat/stream` 返回 SSE。关键事件类型包括：

| `type` | 含义 |
| --- | --- |
| `agent_run` | 本轮 `runId` / `sessionId` / `runtimePath`（固定 `cognitive_finance`） |
| `status` | 阶段提示（如 classifying） |
| `token` | 增量回答文本 |
| `clarification` | Cognitive `ASK_USER`，需用户补充 |
| `done` | 本轮结束 |
| `error` | 失败；不会自动切到第二套编排路径 |

前端只展示阶段与文本，不决定 Cognitive / Domain 内部路由，也不能绕过 Capability 白名单直接调用任意 MCP tool。

更完整的字段与恢复语义以当前 `chat.js` 与 orchestrator `api/routes.py` 为准。
