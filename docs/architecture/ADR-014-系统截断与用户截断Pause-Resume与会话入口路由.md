# ADR-014：系统截断与用户截断（Pause / Resume）与会话入口路由

> 状态：APPROVED  
> 批准人：项目 owner  
> 日期：2026-08-11  
> 实现状态（2026-08-17）：Turn Router、`pending_*`、Pause API / Console Esc **已接线**；**真实 checkpoint 断点续跑尚未关闭**（统一架构 §3 记为 `CURRENT`/`TARGET`，实施 Prompt 缺口 **G1**）。仅重放用户 objective 的 resume **不算**本 ADR 完成。  
> 依赖：架构 §8.1 标识符、§9.2 运行状态、§12 API；Chat Session `pending_*`  
> 影响：[00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) §2.1、§8.1、§8.3、§9、§12；[00-BDLH-Agent-Runtime生产开发实施Prompt.md](../prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md)  
> 依据：桌面《系统截断与用户截断-Resume方案》与现网 `interrupt` + `pending_*` + `/resume` 路径的合成

## 1. 决策目标

把「停下来」统一建模为可恢复暂停，并冻结同 `session_id` 下一条消息的入口路由规则：

1. **系统主动截断**（Graph `interrupt()` / 策略等待点）与 **用户主动截断**（Esc → Pause）共用同一套 Java Run State + `pending_*` 恢复协议；
2. 主交互保持普通打字，不依赖「继续 / 换题」专用按钮面板；
3. 有 `pending` 时**禁止默认盲目 resume**——必须经 Turn Router 判定 `resume` / `new_turn` / `ask_which`。

本 ADR 的实现按统一架构 §18 落到当前唯一运行路径；运行时行为按生产标准，不保留「开发可降级」或仅前端截流的旧恢复路径。

## 2. 背景：现状缺口

代码与架构已具备：

- `session_id` / 内部 `thread_id` / `run_id`；
- Chat Session `pending_run_id` / `pending_thread_id` / `pending_checkpoint_id`；
- 系统 `interrupt()` → 写 pending → `Command(resume=...)` 或 `POST .../resume`。

缺口：

- 用户 Esc 未定义为可恢复 Pause（仅 abort SSE ≠ Pause）；
- 有 pending 时 chat 路径倾向直接 resume，同 session 换方向易误续跑；
- Run 状态缺少与用户暂停对称的 `PAUSED_BY_USER`。

## 3. 标识符与书签（沿用并收紧）

| 标识 | 语义 | 约束 |
|---|---|---|
| `user_id` | 认证用户 | **仅 JWT `sub`**；禁止请求体冒充 |
| `session_id` | 前端会话目录 | 同会话换方向不换 `session_id` |
| `thread_id`（公开） | Chat 路径上等于 `session_id` | 前端可不感知内部 key |
| `thread_id`（内部） | Run State key：`user:{user_id}:thread:{public}` | 仅服务端 |
| `run_id` | 单次 Graph/API 执行 | 与 `thread_id` 不得混用 |
| `pending_*` | 可恢复书签 | `pending_run_id` / `pending_thread_id` / `pending_checkpoint_id` |

关系：

```text
sessionId ──1:1──► public threadId
sessionId ──1:N──► runId
runId     ──► RunRegistry ──► {internal threadId, checkpointId, status}
ChatSession.pending_* ──► 当前可恢复的那一次 run（默认同时至多一个）
```

生产 Run Registry 必须持久化 `run_id → {thread_id, user_id, checkpoint_id, status}`；恢复时校验三者与认证用户一致。

## 4. 两类截断的统一定义

### 4.1 系统主动截断

触发：图节点调用 `interrupt()`，或系统策略在安全点等待用户/策略输入。

落点：

1. Java Data Plane 持久化可恢复 Run State；
2. Run 状态 → `WAITING_USER`；
3. `ChatSession.set_pending(...)`；`pause_reason=system_interrupt`；
4. SSE 发出等待类事件（如 `clarification` / `run.interrupted`）并以 `done` 结束本轮流。

说明：不强制「缺股票代码必须 interrupt」。能在进图前解析/校验的，应前置解决。

### 4.2 用户主动截断（Esc → Pause）

产品默认：**Esc = Pause（可 resume），不是 Cancel。**

```text
仅前端砍流 ≠ Pause
Pause = 前端停收流 + 后端协作停止 + checkpoint + pending 书签
```

后端 Pause：

1. 校验 run 归属且状态为 `RUNNING`；
2. 置位 `pause_requested`；禁止启动新的高成本 LLM/Capability 调用；
3. 在安全点停止（节点边界、单次 Capability/模型调用结束后）；不保证半截 token 精确续写；
4. Run → `PAUSED_BY_USER`；写/刷新 pending；`pause_reason=user_pause`；
5. 返回 `resumable=true` 的 PauseAck。

### 4.3 Cancel（对照）

若产品提供「停止并丢弃」：旧 run → `CANCELLED`/`ABANDONED`，清理 pending，**不可**再 resume；下一句同 session 开新 `run_id`。

## 5. Run 状态机

```text
RUNNING
WAITING_USER          # 系统主动截断
PAUSED_BY_USER        # 用户 Pause
COMPLETED
FAILED
CANCELLED / ABANDONED
```

转移：

```text
RUNNING ──系统 interrupt──► WAITING_USER
RUNNING ──用户 Pause─────► PAUSED_BY_USER
WAITING_USER / PAUSED_BY_USER ──resume──► RUNNING
WAITING_USER / PAUSED_BY_USER ──abandon──► CANCELLED/ABANDONED
任意非终态 ──不可恢复错误──► FAILED
```

`ChatSession` 逻辑投影（权威进度仍在 Java Run State + Run Registry）：

```text
active_run_id?
run_status?
pause_reason?              # system_interrupt | user_pause | null
pending_run_id / pending_thread_id / pending_checkpoint_id
awaiting_route_confirm?    # 会话层分流确认中
```

## 6. Turn Router（同 session 下一条消息）

主入口仍是 `POST /api/v1/chat/stream`，Body 稳定传 `sessionId` + `message`（+ mode/regenerate 等）；身份只走 JWT。

```text
有 pending？（WAITING_USER 或 PAUSED_BY_USER）
  ├─ 强信号继续 / 回答挂起问题 → resume 同一 run_id
  ├─ 强信号换方向 / 取消旧任务 → abandon 旧 run，清 pending，新 run_id
  └─ 不清晰 → ask_which（会话层分流确认）
        · 不 resume、不跑主分析图
        · 回一句普通 assistant 确认
        · 保留 pending；可设 awaiting_route_confirm=true
```

原则：

1. 强信号直接决策，不打扰用户；
2. 弱信号才多问一句；
3. **拿不准时禁止擅自 `Command(resume)`**；
4. Turn Router 不是 Graph `interrupt()`，也不是 Memory / Context 的职责。

同 session 换方向时：

| 数据 | 行为 |
|---|---|
| `session_id` / 公开 thread / L1 聊天历史 | 复用 |
| 未完成 run / pending / interrupt 书签 | **abandon，不复用** |
| thread 内 entities（弱上下文） | 可保留，以新消息为准覆盖 |
| 用户级画像 / 持仓（L4） | 可跨 run 使用 |
| `run_id` | **必须新开** |

一句话：**复用对话记忆，不复用未完成执行。**

## 7. API 与 SSE

生产保留并扩展：

```text
POST /api/v1/chat/stream
POST /api/v1/agent-runs/{run_id}/pause
POST /api/v1/agent-runs/{run_id}/resume
POST /api/v1/agent-runs/{run_id}/cancel    # 可选对称；不可 resume
```

Pause 响应至少包含：`runId`、`sessionId`、`status=PAUSED_BY_USER`、`checkpointId`、`resumable`。

SSE 建议增加或对齐：`run.interrupted`、`run.paused`、`run.resumed`；等待态必须以 `done` 结束本轮流，避免前端空转。

## 8. 与 Memory / Context 的边界

- 执行进度与可否 resume：**只认** Java Run State + Run Registry + `pending_*`（ADR-011 的 L0 工作记忆与 L1 会话书签投影）；
- **禁止**用 Mem0「记住停在哪一步」替代 Run State；
- Context 组装（ADR-015）在 Turn Router 判定之后执行；`ask_which` 可用极简上下文，不召回大量 L3。

## 9. 实施与验收要点

1. Esc 后未收到 PauseAck/`resumable=true` 前，前端不得宣称可继续；
2. 「继续」复用同一 `run_id`；明确换题则新 `run_id`、`session_id` 不变；
3. 含糊句只确认、不推进主分析；
4. 系统 interrupt 与用户 Pause 共用 pending 字段，不发明第二套会话恢复键；
5. 跨用户无法 pause/resume/读 pending；生产 Registry 与 Session 必须持久化，重启后可按 `run_id` 定位。

## 10. 后果

正面：补齐产品级可恢复暂停，并堵住「有 pending 就误 resume」的行为洞。

代价：需实现协作式停止与入口路由；“有 pending 直接 resume”的错误路径必须直接删除并补回归测试。
