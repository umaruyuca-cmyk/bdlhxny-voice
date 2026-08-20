# BDLH Agent Runtime 前端 · 后端对接说明

> 本文档说明前端页面如何与后端对接：页面地址、路由、API 契约与 SSE 事件流。
> 前端通过 dev-server 反向代理把所有 `/api/*` 请求转发到后端，前端页面本身不关心后端地址。
> 旧双 Agent 工作站（`workspace.html`）已删除；`/workspace` 永久重定向到 `/agent`。

---

## 1. 页面地址（联调用）

前端 dev-server 默认端口 `8082`，也可用 `PORT` 环境变量覆盖。下表使用默认端口。

| 页面 | 地址 | 说明 |
| --- | --- | --- |
| 首页 | `http://127.0.0.1:8082/` | 首屏入口 |
| 统一助手 | `http://127.0.0.1:8082/agent` | Cognitive + Finance 唯一产品对话入口 |
| `/workspace` | 301 → `/agent` | 旧入口兼容重定向 |
| 文档中心 | `http://127.0.0.1:8082/docs` | 用户与开发者文档索引 |
| Skill 接入规范 | `http://127.0.0.1:8082/docs/skill` | 通用 Skill 接入文档 |
| Agent 与路由 | `http://127.0.0.1:8082/docs/agents` | 领域分析说明 |
| Skill 生态 | `http://127.0.0.1:8082/skill-dashboard.html` | 多 Skill 服务目录 |
| API 联调页（开发工具） | `http://127.0.0.1:8082/api-console.html` | 仅开发人员测试 SSE 与运行记录 |

### 页面联动参数
- `?q=问题内容` —— 自动带入并发送问题（首页输入框跳转时带上）
- 历史 `?name=` / `?mode=` 双 Agent 分流参数已退役，不再决定后端编排路径

---

## 2. 前端 → 后端 API 契约

前端调用以下接口（全部经 `/api/*` 代理转发，方法、路径、请求体原样透传）。

### 2.1 流式对话（SSE）

```
POST /api/v1/chat/stream
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "message": "...",
  "sessionId": "...",   // 可选
  "regenerate": false   // 可选
}
```

由 Python Cognitive Orchestrator 执行；`runtimePath` 固定为 `cognitive_finance`。失败不会回退到第二套编排图。

### 2.2 会话目录与消息

- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{sessionId}`
- `DELETE /api/v1/conversations/{sessionId}`

### 2.3 认证与用户事实

- 认证：`/api/v1/auth/*` → Java
- 持仓/画像等用户事实：Java Data Plane 只读接口（经 JWT）

更细字段以 `CHAT_INTEGRATION.md`、`chat.js` 与 orchestrator/Java OpenAPI 为准。
