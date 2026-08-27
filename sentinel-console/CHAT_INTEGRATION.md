# 对话页（chat.html）· 后端对接

适用页面：`public/chat.html` + `public/assets/chat-theme.css` + `public/assets/chat.js`，以及 Block 渲染器 `public/assets/blocks.js`、徽标 `public/assets/badges.js`。

产品权威描述见 [`docs/architecture/00-Sentinel产品设计与架构.md`](../docs/architecture/00-Sentinel产品设计与架构.md) §6.2 / §7.4 / §7.6 / §7.8。本文档对齐**当前实现**，供联调使用。

正式入口为 `/lab`：固定分析用例 + 真实 LLM，无会话、无自由输入、无 mock。`/agent` 与 `/workspace` 永久重定向到 `/lab`。看护首页追问抽屉 iframe 装入 `/lab?sessionId=&followup=&embed=1`。

---

## 1. 页面与运行方式

| 项 | 值 |
| --- | --- |
| 页面地址（联调） | `http://127.0.0.1:8082/lab` |
| 追问入口 | `/lab?sessionId={id}&followup={事件摘要}`；抽屉内加 `embed=1`，固定用例 |
| 真实 LLM | 引擎需配置 `LLM_API_KEY`；`LLM_UNAVAILABLE` 时 lab 标记失败，不用 mock |
| 静态服务 | `node dev-server.js`，默认端口 `8082`（`PORT` 可覆盖） |
| API 代理 | 认证 / 持仓 → Java `127.0.0.1:8081`（`BDLH_RUNTIME_BACKEND_URL`）；聊天 / 会话 / 通知 / 运行控制 / ready → Python `127.0.0.1:8090`（`BDLH_RUNTIME_ANALYSIS_URL`） |
| 前端构建 | 无构建；ECharts CDN **单** script |

前端只请求同源相对路径 `/api/v1/*`，不感知后端真实地址。身份只走 `Authorization: Bearer {JWT}`，不把 `userId` 放进 URL。

---

## 2. API 一览

| # | 方法 | 路径 | 用途 | 必需性 |
| --- | --- | --- | --- | --- |
| 1 | POST | `/api/v1/chat/stream` | 会话通道 SSE | **必需** |
| 2 | GET | `/api/v1/conversations?limit=30` | 会话目录 | 可选（失败静默降级为本地列表） |
| 3 | GET | `/api/v1/conversations/{sessionId}` | 会话消息快照 | 可选 |
| 4 | DELETE | `/api/v1/conversations/{sessionId}` | 删除服务端会话 | 已实现 |
| 5 | POST | `/api/v1/agent-runs/{runId}/pause` | 运行中暂停 | 运行控制 |
| 6 | POST | `/api/v1/agent-runs/{runId}/cancel` | 放弃当前 run | Esc 中断 |
| 7 | GET | `/api/v1/ready` | 依赖降级提示条 | 可选 |

Python 只信任 JWT 的 `sub` 作为 `user_id`。请求体不得自行声明其他用户身份。

`POST /api/v1/chat/stream` 请求体：

```json
{
  "sessionId": "...",
  "message": "...",
  "regenerate": false,
  "enabledSkillIds": []
}
```

`enabledSkillIds` 为兼容字段：产品会话页固定传空数组。工具装载由引擎 scoped|search + 治理中间件决定，前端不再提供「插件启停」UI。

暂停后恢复**不**另开一条 resume SSE：前端发送「继续」，由 Turn Router 在同一 `sessionId` 上恢复 checkpoint。

---

## 3. SSE 事件契约（§6.2 / §7.6）

`POST /api/v1/chat/stream` 以 `text/event-stream` 返回。前端用 `response.body.getReader()` 解析 `data:` 行，**不**使用 `EventSource`。

| `type` | 载荷 | UI |
| --- | --- | --- |
| `agent_run` | `runId` / `sessionId` / `runtimePath` | 进入运行态，显示暂停按钮；如有 `degraded` 则提示 |
| `tool.step` | `tool` / `arguments` / `status`；可选 `elapsedMs` / `auditCode` / `query` / `hitCount` | 工具轨迹追加或更新节点（pending → ✓ / ✕）。`search_tools` 特殊渲染：检索词 + 命中数 |
| `token` | `content` 文本分片 | 正文增量渲染（真实 LLM `astream`，禁止前端定长切片） |
| `response.final` | ChatResult v2 | 定格工具轨迹；渲染 `blocks[]`、证据链、审计码、披露 |
| `done` | `status`：`COMPLETED` / `NEED_CLARIFICATION` / `FAILED` | 收尾；澄清选项卡或错误条 |
| `clarification` | `prompt` / `options` | 输入框上方与消息内澄清选项卡（对应 `NEED_CLARIFICATION`） |
| `guardrail.blocked` | `message` / `auditCode` | 护栏拦截文案 |
| `run.paused` | `resumable` | 显示恢复按钮 |
| `status` | `step` | 阶段提示；`degraded` / `memory_degraded` 映射降级条 |
| `error` | `message` | 错误文案 |

`notification` 事件属于看护通道，见 `API_INTEGRATION.md`，不在本页消费。

---

## 4. ChatResult v2 与 ResultBlock（§7.8）

`response.final`：

```text
{
  answer,                 // LLM 解读文本（叙事层；通常已由 token 流过）
  blocks[],               // 工具 Observation 直接投影（事实层，前端不重算数字）
  tool_trace,
  evidence_refs,
  audit_codes,
  disclosures
}
```

`blocks[].type` ∈ `ScoreCard` | `AnalysisReport` | `SuitabilityDraft` | `PortfolioHealth` | `QuoteTable`。未知类型由 `blocks.js` 降级为折叠 JSON，不报错、不丢弃。

展示顺序：流式 `answer` → Block 卡片 → 证据链卡（`evidence_refs` / `audit_codes` / `disclosures`）。

SuitabilityDraft 守 C-2：标题为风险匹配筛查（DRAFT）；匹配项与风险项成组；披露固定为「本结果仅为风险匹配筛查草稿，不构成投资建议。」；界面不出现「适合 / 推荐买入」。
