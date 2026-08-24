# Sentinel 实施 Prompt（执行真源）

| 项 | 值 |
|---|---|
| 文档状态 | `ACTIVE`（实施期唯一执行真源） |
| 创建日期 | 2026-08-18 |
| 上游文档 | [00-Sentinel产品设计与架构.md](../architecture/00-Sentinel产品设计与架构.md)（设计真源，下称「设计文档」）、[00-仓库文件管理树.md](../00-仓库文件管理树.md)（文件归属，下称「文件树」） |
| 适用对象 | 任何执行本实施的 AI 或工程师；每张工单自包含，可独立读取执行 |

---

## 0. 执行纪律（所有工单通用，违反即返工）

1. **术语纪律**：只使用设计文档已定义的名词——`ToolCard`（§4.1）、工具装载 `scoped|search`（§4.2）、治理中间件 G1–G7（§4.4）、语义快路径（§4.6）、`WatchEvent` / `watch_rule` / `dedupe_key`（§4.8）、唤醒包（§4.5）、结果块 `ResultBlock`（§7.8）、约束 C-1~C-5（§1.3）。**不得自造名词**；确需新概念时先回报，补进设计文档后再用。
2. **状态机**：每张工单状态取值仅 `未完成` / `进行中` / `完成`。开工时置 `进行中`；验收通过后置 `完成` 并回填「完成时间 + 验证证据（命令输出摘要）」。本文档状态字段由执行者就地更新。
3. **代码处置类型**：工单内每个文件标注【新增】【修改】【删除】【保留引用】之一：
   - 【新增】文件不得与既有文件重名覆盖；
   - 【修改】必须先读全该文件，做最小差异修改，**不得整文件覆写**；未涉及的行为保持原样；
   - 【删除】以工单清单为准，删除前全局检索确认引用为零，并同步删除其专属测试；
   - 【保留引用】只读复用，不得改动。
4. **一致性纪律**：执行中发现现状与工单描述不一致（文件不存在、行号漂移、行为不符），**停止该工单**，在工单下追加「偏差记录」，修正工单后再执行；不得擅自变更设计。
5. **测试门禁**：每个阶段出口执行——Python：`cd sentinel-engine && uv run pytest -q` 与 `uv run ruff check`；Java：`cd sentinel-data && mvn -B -ntp test`（本阶段涉及 Java 时）；前端：`cd sentinel-console && npm test`（本阶段涉及前端时）。任一失败则工单不得置 `完成`。
6. **数据库纪律**：结构变更改 `db/postgresql/schema/` 与 `db/postgresql/seed/` 全量脚本；同时在 `db/execution/` 新增一份 `YYYYMMDD_说明.md` 执行说明，并把 `db/README.md` 与 `db/execution/README.md` 的「当前基线」链接改到最新文件。应用启动不得执行 DDL。
7. **基线先行**：T0 第一张工单先记录当前测试基线数值，后续阶段只允许增长不允许减少（工单明确删除的测试除外，删除数须在工单「完成证据」中注明）。

## 0.1 工单状态总览

| 工单 | 标题 | 状态 |
|---|---|---|
| WO-T0-1 | 基线确认与记录 | `未完成` |
| WO-T0-2 | 演示 seed 数据 | `未完成` |
| WO-T0-3 | 演示部署档配置 | `未完成` |
| WO-T1-1 | watch 数据表 | `未完成` |
| WO-T1-2 | watch 包骨架与事件契约 | `未完成` |
| WO-T1-3 | 价格阈值事件源 | `未完成` |
| WO-T1-4 | 晨报 / 盘后定时事件源 | `未完成` |
| WO-T1-5 | 唤醒上下文组装器 | `未完成` |
| WO-T1-6 | 通知落库与追问闭环 | `未完成` |
| WO-T1-7 | 演示注入端点 | `未完成` |
| WO-T1-8 | 看护环测试 | `未完成` |
| WO-T2-1 | 工具目录（ToolCard） | `未完成` |
| WO-T2-2 | 治理中间件 | `未完成` |
| WO-T2-3 | Agent 循环与 scoped 装载 | `未完成` |
| WO-T2-4 | tool search 装载模式 | `未完成` |
| WO-T2-5 | eval 题库与双模式对照 | `未完成` |
| WO-T2-6 | 装配切换与旧路径删除 | `未完成` |
| WO-T3-1 | SSE 契约 v2（真流式） | `未完成` |
| WO-T3-2 | ChatResult v2 与 blocks 投影 | `未完成` |
| WO-T3-3 | 看护首页 dashboard | `未完成` |
| WO-T3-4 | 追问抽屉与 Block 渲染器 | `未完成` |
| WO-T3-5 | 前端契约测试与对接文档重写 | `未完成` |
| WO-T4-1 | 一键演示 compose | `未完成` |
| WO-T4-2 | 文档终稿同步 | `未完成` |
| WO-T4-3 | 演示彩排与录屏 | `未完成` |

---

## 1. 阶段 T0：基线与演示数据

### WO-T0-1 基线确认与记录

- 状态：`未完成`
- 对应设计：§10 T0、§11.3
- 目的：记录实施前的测试基线，作为后续所有阶段的回归参照。

**处置清单**：无代码改动。

**实施要求**：

1. 执行 `cd sentinel-engine && uv run pytest -q`，记录通过数；执行 `uv run ruff check`；
2. 执行 `cd sentinel-data && mvn -B -ntp test`，记录结果；
3. 执行 `cd sentinel-console && npm test`，记录结果；
4. 在本工单「完成证据」回填三组数值。

**验证方式**：上述命令全部退出码为 0。

**完成证据**：（回填：pytest 数 / ruff 结果 / mvn 结果 / npm 结果 / 日期）

### WO-T0-2 演示 seed 数据

- 状态：`未完成`
- 对应设计：§10 T0、§5
- 目的：空库初始化后即得可演示的持仓与风险画像。

**处置清单**：

- 【新增】`db/postgresql/seed/demo_sentinel.sql`
- 【新增】`db/execution/YYYYMMDD_演示seed.md`（文件名日期取执行当日）
- 【修改】`db/README.md`、`db/execution/README.md`（基线链接指向新执行说明）

**保留引用**（先读，确认目标表结构后写 seed，不得凭记忆写字段）：`db/postgresql/schema/financial_user_data.sql`（持仓 `portfolio_positions`、用户配置 `user_configs`、风险画像相关表）。

**实施要求**：

1. seed 内容：演示用户（与单用户模式 `BDLH_RUNTIME_SINGLE_USER_ID` 取值对齐，先读 `deploy/.env.example` 中该键的注释确认口径）；持仓 4 只（须含宁德时代 300750）；稳健型风险画像；
2. 文件头部注释标明「演示数据，非生产事实」；
3. 目标记忆（如「两年内换房」）**不落库**——该事实经运行时确认卡写入 L3（设计文档 §4.6），演示时现场产生或由 WO-T1-6 完成后经记忆候选接口注入；
4. 执行说明写明：变更摘要、是否清空重建、完整执行顺序、验收要点。

**验证方式**：空库按新基线执行全部脚本后，Java 数据面持仓接口与风险画像接口返回演示数据；`mvn -B -ntp test` 不劣化。

**完成证据**：（回填）

### WO-T0-3 演示部署档配置

- 状态：`未完成`
- 对应设计：§4.8（演示注入）、§6.1、C-4
- 目的：登记演示部署档开关，供 WO-T1-7 与前端水印使用。

**处置清单**：

- 【修改】`sentinel-engine/src/bdlh_runtime/config.py`（新增配置项 `demo_mode: bool`，环境变量 `BDLH_DEMO_MODE`，默认 `false`；先读该文件现有 Settings 写法，沿用同一风格）
- 【修改】`deploy/.env.example`（登记 `BDLH_DEMO_MODE=false` 及中文注释：演示部署档，开启后注册演示注入端点并显示演示标识）
- 【修改】`deploy/.env.ci`（追加同名键，保持 CI compose 校验通过）

**验证方式**：`uv run pytest -q` 全绿；配置单测覆盖默认值与显式开启两态（新增测试随本工单提交）。

**完成证据**：（回填）

---

## 2. 阶段 T1：看护环

> 阶段目标：事件 → 唤醒 → 解读 → 通知 → 追问闭环全程走通。本阶段允许事件解读仍由现行编排链路产出（引擎替换在 T2 完成，届时看护环不改一行）。

### WO-T1-1 watch 数据表

- 状态：`未完成`
- 对应设计：§5、§4.8
- 处置清单：

| 文件 | 处置 |
|---|---|
| `db/postgresql/schema/watch.sql` | 【新增】 |
| `db/execution/YYYYMMDD_watch表.md` | 【新增】 |
| `db/README.md`、`db/execution/README.md` | 【修改】基线链接 |

**实施要求**：

1. `watch_rule`：`id`、`user_id`、`type`（`price_threshold` / `daily_briefing` / `post_market_review`）、`config JSONB`、`status`（`active` / `paused`）、`last_fired_at`、审计时间列；表与列注释完整（参照既有 schema 文件的注释风格，先读 `db/postgresql/schema/task_messaging.sql`）；
2. `watch_event`：`id`、`rule_id`、`type`、`source`、`payload JSONB`、`dedupe_key`、`occurred_at`；**`dedupe_key` 上唯一约束**（幂等的物理承载，设计文档 §4.8）；`source` 取值含 `demo_inject`（C-4）；
3. 两表落 `runtime` schema（先读 `db/postgresql/bootstrap.sql` 确认 schema 清单）。

**验证方式**：空库按新基线执行成功；重复插入相同 `dedupe_key` 报唯一冲突（验收要点写入执行说明）。

**完成证据**：（回填）

### WO-T1-2 watch 包骨架与事件契约

- 状态：`未完成`
- 对应设计：§4.8、文件树 §3
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/watch/__init__.py` | 【新增】 |
| `sentinel-engine/src/bdlh_runtime/watch/events.py` | 【新增】 |

**实施要求**：

1. `events.py` 以 pydantic 定义 `WatchEvent`（字段同 WO-T1-1）与 `WatchRule` 视图模型；`dedupe_key` 生成函数集中于此（规则 × 触发窗口 × 方向）；
2. 包注释引用设计文档 §4.8；`watch/` 不得 import `cognitive/`、`guardrails/` 以外的引擎内部件之外的内容——即仅允许依赖 `runtime/`、`domain/`、`contracts/`（内核纯净度测试要求：先读 `sentinel-engine/tests/architecture/test_kernel_purity.py` 确认既有断言口径，新增包不得引入域字面量）。

**验证方式**：`uv run pytest -q` 全绿（含架构纯净度门禁）。

**完成证据**：（回填）

### WO-T1-3 价格阈值事件源

- 状态：`未完成`
- 对应设计：§4.8（边沿触发 / 轮询纪律）
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/watch/sources.py` | 【新增】 |

**保留引用**（只读复用，先读后用）：

- `sentinel-engine/src/bdlh_runtime/runtime/scheduler.py`（M6 调度回路，事件源的挂载点）
- `sentinel-engine/src/bdlh_runtime/runtime/tasks.py`、`runtime/remote_tasks.py`（M6 价格任务底座：`financial_task` 轮询与结果获取）
- `sentinel-engine/src/bdlh_runtime/domain/trading_calendar.py`（交易日 / 交易时段判定）
- `sentinel-engine/src/bdlh_runtime/tools/java_data_adapter.py`（持仓与行情相关数据面调用）

**实施要求**：

1. 轮询器仅在交易时段运行（交易日历判定），非交易时段不发起请求；
2. 活跃规则按标的聚合后批量取价；越阈判定为**边沿触发**（与 `watch_rule.last_fired_at` 及当日已存事件的 `dedupe_key` 联合判定，杜绝水平重复触发）；
3. 产出 `WatchEvent` 经 WO-T1-2 契约落库；数据源失败指数退避并记日志，不中断轮询循环；
4. 全程不改写【保留引用】文件的行为；确需扩展时以新增函数方式叠加。

**验证方式**：`tests/watch/test_sources.py`（WO-T1-8）覆盖：交易时段判定、穿越触发、同向重复不触发、失败退避。

**完成证据**：（回填）

### WO-T1-4 晨报 / 盘后定时事件源

- 状态：`未完成`
- 对应设计：§4.8、§2.1 F1
- 处置清单：`sentinel-engine/src/bdlh_runtime/watch/sources.py`【修改】（新增 cron 类事件源函数）

**实施要求**：

1. `daily_briefing`（默认 08:30）与 `post_market_review`（默认 16:30）两类规则，仅在交易日产出事件；
2. 事件负载只含触发事实（交易日、规则配置），**不含资讯内容**——内容由唤醒后的 Agent 运行现取（设计文档 §4.8：晨报内容不在事件源生成）；
3. `dedupe_key` = 规则 × 交易日。

**验证方式**：交易日 / 非交易日 / 重复触发三态单测通过。

**完成证据**：（回填）

### WO-T1-5 唤醒上下文组装器

- 状态：`未完成`
- 对应设计：§4.5（唤醒态）、§4.6（记忆召回注入）
- 处置清单：`sentinel-engine/src/bdlh_runtime/watch/wakeup.py`【新增】

**保留引用**：`sentinel-engine/src/bdlh_runtime/runtime/remote_runtime_data.py`（持仓 / 画像取数）、`sentinel-engine/src/bdlh_runtime/memory/recall.py`（L3 召回）、`sentinel-engine/src/bdlh_runtime/runtime/application.py`（引擎装配入口，唤醒运行经此处进入）。

**实施要求**：

1. 输入 `WatchEvent` + `user_id`，输出「唤醒包」：解读系统提示引用 + 事件负载 + 持仓快照 + 风险画像 + L3 目标记忆（召回失败记 `memory_degraded` 标记，不阻断）；
2. 唤醒运行复用现行编排入口（本阶段引擎未替换，解读产出走现行链路）；
3. 系统提示文件落 `sentinel-engine/prompts/scene_wakeup.md`【新增】，按设计文档 §4.8 输出结构（标题 / 摘要 / 证据引用 / 审计码 / 严重度）与 C-1 / C-2 口径撰写；代码内不得内联长提示字符串。

**验证方式**：组装器单测（数据面与记忆以 Fake 注入）：唤醒包字段完整；记忆缺失时带降级标记。

**完成证据**：（回填）

### WO-T1-6 通知落库与追问闭环

- 状态：`未完成`
- 对应设计：§4.8（产出 / 追问闭环）、§6.1
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/watch/notify.py` | 【新增】（解读结果 → 通知写入） |
| `sentinel-engine/src/bdlh_runtime/api/routers/notifications.py` | 【修改】（新增 `POST /{id}/followup`） |
| `sentinel-engine/src/bdlh_runtime/runtime/chat_sessions.py` | 【修改】（支持携带初始事件上下文建会话） |

**保留引用**：`sentinel-engine/src/bdlh_runtime/runtime/remote_run_state.py`（run 引用持久化）；Java 侧 `NotificationController`（先读 `sentinel-data/src/main/java/com/bdlh/runtime/api/NotificationController.java` 确认既有通知契约，复用不落新表）。

**实施要求**：

1. 通知记录携带 `run_id`、事件摘要、严重度；同一运行结果只产生一条通知（与 run 结果唯一绑定）；
2. `followup` 创建会话并将事件摘要注入首轮上下文；返回 `session_id` 供前端直接进入追问；
3. 演示注入事件产生的通知，`payload.source=demo_inject` 必须透传至通知记录（C-4）。

**验证方式**：集成测试——注入 WatchEvent → 通知落库（字段断言）→ followup 建会话首轮上下文含事件摘要；重复运行不重复通知。

**完成证据**：（回填）

### WO-T1-7 演示注入端点

- 状态：`未完成`
- 对应设计：§4.8、§6.1、C-4
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/api/routers/demo_events.py` | 【新增】 |
| `sentinel-engine/src/bdlh_runtime/runtime/application.py` | 【修改】（仅 `demo_mode=true` 时注册该路由） |

**实施要求**：

1. `POST /internal/demo/events`：请求体为事件类型与负载（如 `{type:"price_threshold", symbol:"300750", pct:-5.2}`），写入 `source=demo_inject` 的 `WatchEvent`，走与真实事件完全相同的后续链路；
2. 非 demo 档下路由不注册（404）；不得仅依赖「隐藏」；
3. 响应返回生成的事件 id，供演示脚本轮询通知到达。

**验证方式**：契约测试覆盖两档（开 / 关）；注入后事件带 `demo_inject` 标记贯穿至通知。

**完成证据**：（回填）

### WO-T1-8 看护环测试

- 状态：`未完成`
- 对应设计：§11.1
- 处置清单（均【新增】）：

| 文件 | 覆盖 |
|---|---|
| `sentinel-engine/tests/watch/__init__.py`、`tests/watch/test_sources.py` | 交易日判定、边沿触发、去重幂等、失败退避 |
| `sentinel-engine/tests/watch/test_wakeup_flow.py` | 注入事件 → 唤醒 → 通知落库（证据引用、审计码断言；LLM 以既有 Fake 方式注入，参照 `tests/helpers_application.py` 的装配模式） |
| `sentinel-engine/tests/api/test_demo_events.py` | demo 档开 / 关路由注册、`source` 全链路透传 |

**验证方式**：`uv run pytest -q` 全绿且测试数较基线净增（WO-T0-1 记录值 + 本阶段新增数）。

**完成证据**：（回填）

---

## 3. 阶段 T2：工具层

> 阶段目标：统一工具目录 + 原生 tool calling 循环 + 治理中间件 + 双模式装载；完成后旧意图路由与域插件框架物理删除。

### WO-T2-1 工具目录（ToolCard）

- 状态：`未完成`
- 对应设计：§4.1
- 处置清单：`sentinel-engine/src/bdlh_runtime/tools/catalog.py`【新增】

**保留引用**：`sentinel-engine/src/bdlh_runtime/tools/capabilities.py`（现有能力清单，迁移数据源）、`sentinel-engine/src/bdlh_runtime/integrations/mcp/registry.py` 与 `integrations/mcp/adapter.py`（MCP 工具发现）。

**实施要求**：

1. `ToolCard` 字段严格按设计文档 §4.1（`name` / `description` / `parameters` / `origin` / `read_only` / `required_scope` / `cost_hint`）；
2. 本地工具（行情、持仓、画像、分析引擎、Web 检索、记忆）与 MCP 工具统一登记；目录为唯一真源，装载器 / 检索索引 / 中间件均从目录读取；
3. `description` 面向「模型选择 + embedding 检索」双目的撰写；
4. **目录中不得注册任何交易执行语义的工具（C-1）**。

**验证方式**：目录单测（字段完整性、`read_only` 标记覆盖、MCP 工具代理登记）。

**完成证据**：（回填）

### WO-T2-2 治理中间件

- 状态：`未完成`
- 对应设计：§4.4（G1–G7）
- 处置清单：`sentinel-engine/src/bdlh_runtime/guardrails/middleware.py`【新增】

**保留引用**：`sentinel-engine/src/bdlh_runtime/guardrails/policies.py`、`guardrails/interfaces.py`、`guardrails/contracts.py`（既有四时点检查逻辑——中间件复用其检查函数，本工单不删除这些文件）。

**实施要求**：

1. 拦截链顺序固定为 G1 可见性 → G2 只读 → G3 权限 → G4 预算 → G5 参数校验 → 执行 → G6 Observation 包装 → G7 审计记录；任一前置拦截即终止并返回结构化拒绝（含审计码）；
2. 中间件对本地工具与 MCP 工具一致生效；新增工具无需治理侧适配；
3. 审计记录字段：调用者、工具名、参数摘要、耗时、结果状态、审计码。

**验证方式**：G1–G7 逐条单测（含幻觉工具名拒绝、预算耗尽、参数非法）；全量回归。

**完成证据**：（回填）

### WO-T2-3 Agent 循环与 scoped 装载

- 状态：`未完成`
- 对应设计：§4.2、§4.3（三层闸门）
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/engine/__init__.py`、`engine/loop.py`、`engine/loader.py` | 【新增】 |
| `sentinel-engine/prompts/system_base.md`、`prompts/scene_chat.md`、`prompts/scene_direct.md` | 【新增】 |

**保留引用**：`sentinel-engine/src/bdlh_runtime/runtime/llm.py`（`create_llm`，LangChain `ChatOpenAI` 构造）；`sentinel-engine/src/bdlh_runtime/cognitive/semantic_router/`（快路径，整包保留）。

**实施要求**：

1. `loop.py`：`bind_tools` 原生 tool calling 循环——模型输出 `tool_calls` → WO-T2-2 中间件 → Observation 回填 → 直至模型产出最终回答或预算耗尽；无 `tool_calls` 时直接应答（设计文档 §4.3 G-β）；
2. `loader.py`：`scoped` 策略——场景标签 → 工具包映射表（代码内常量，3–4 行量级）；场景标签来自语义快路径；
3. 会话上下文：最近 N 轮消息 + L3 召回注入消息序列（N 为配置项，默认 10）；
4. 系统提示从 `prompts/` 文件加载，禁止内联长字符串；
5. 无 LLM Key 环境：循环不启动，走现行降级路径，`/ready` 报 degraded（沿用 `runtime/readiness.py` 既有机制）。

**验证方式**：FakeChatModel 集成测试（构造 `tool_calls` / 纯文本两类返回）；上下文与记忆注入断言；全量回归。

**完成证据**：（回填）

### WO-T2-4 tool search 装载模式

- 状态：`未完成`
- 对应设计：§4.2（search 策略及补充规则）
- 处置清单：`sentinel-engine/src/bdlh_runtime/tools/search.py`【新增】；`engine/loader.py`【修改】（双策略分发）

**保留引用**：`sentinel-engine/src/bdlh_runtime/cognitive/semantic_router/encoder.py`（embedding 编码器复用）。

**实施要求**：

1. `search_tools(query, top_k=3)` 元工具：对权限过滤后的目录做 embedding 相似度检索，命中 ToolCard 动态装载进后续上下文；权限过滤先于检索（§4.2）；
2. 会话级装载缓存；`search_tools` 调用计入预算；连续 2 次未命中回退 `scoped` 宽包；
3. 配置项 `BDLH_TOOL_LOADING=scoped|search`，默认 `scoped`（登记 `config.py` 与 `deploy/.env.example`）。

**验证方式**：检索命中 / 未命中回退 / 缓存 / 预算扣减四类单测。

**完成证据**：（回填）

### WO-T2-5 eval 题库与双模式对照

- 状态：`未完成`
- 对应设计：§11.2
- 处置清单：`sentinel-engine/tests/eval/__init__.py`、`tests/eval/routing_cases.py`、`tests/eval/run_eval.py`【新增】；报告落 `docs/eval/YYYYMMDD_装载模式对照.md`【新增】（执行当日日期）。

**实施要求**：

1. 题库 ≥40 条：闲聊 / 知识 / 金融研究 / 组合 / 适合度 / 多轮指代 / 误伤 / 看护场景 ≥6 条；
2. 同一题库对 `scoped` 与 `search` 各跑一遍（离线 Fake 驱动 + 可选真实 LLM 标注），输出任务成功率、检索命中率（search 组）、平均轮次、token 消耗对比；
3. 报告含结论与默认策略建议。

**验证方式**：跑批脚本可重复执行并产出结构化结果；报告归档。

**完成证据**：（回填）

### WO-T2-6 装配切换与旧路径删除

- 状态：`未完成`
- 对应设计：§11.3（物理删除纪律）
- 处置清单：

| 文件 / 目录 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/runtime/application.py` | 【修改】（装配切换至 `engine/`；删除域插件装配段） |
| `sentinel-engine/src/bdlh_runtime/cognitive/understand.py`、`cognitive/goal_action_selector.py`、`cognitive/goal_schema.py` | 【删除】（伪 function calling 与规则路由） |
| `sentinel-engine/src/bdlh_runtime/domains/` 整包 | 【删除】（域插件框架，C-5） |
| `sentinel-engine/src/bdlh_runtime/registry/`（如仅服务于域插件装配） | 【删除】（先确认无其他引用） |
| `sentinel-engine/tests/domains/`、`tests/cognitive/test_goal_action_selector.py` 等专属测试 | 【删除】（全局检索确认引用为零后执行） |

**实施要求**：

1. 删除前对每项目标执行全局引用检索并在「完成证据」中列出检索结论；
2. 行为场景迁移按「场景保留、断言重写」：既有测试覆盖的关键行为（快路径分流、只读拦截、适合度闭环、checkpoint 恢复）在 `tests/engine/` 下按新契约重写后方可删除旧测试；
3. 本工单完成后，`cognitive/` 中保留的仅剩快路径与 checkpoint 相关组件；`test_kernel_purity.py` 三断言原样通过。

**验证方式**：`uv run pytest -q` 全绿（完成证据注明删除测试数与重写测试数）；`uv run ruff check` 通过。

**完成证据**：（回填）

---

## 4. 阶段 T3：前端与流式

### WO-T3-1 SSE 契约 v2（真流式）

- 状态：`未完成`
- 对应设计：§6.2
- 处置清单：`sentinel-engine/src/bdlh_runtime/api/routers/chat.py`、`api/sse.py`【修改】

**实施要求**：

1. `token` 事件改为 LLM `astream` 真实流式分片，**删除伪流式切片逻辑**（先读 `chat.py` 定位现有 24 字符切片段，删除并在完成证据中注明行区间）；
2. 新增 `tool.step` 事件（tool / arguments / status 实时外显，含 `search_tools` 检索节点）；`agent_run` 与 `done` 两帧语义不变；
3. `NEED_CLARIFICATION` / 拦截 / 降级三态的事件序列符合设计文档 §6.2 表。

**验证方式**：SSE 契约测试（分片非均质定长、`tool.step` 序列、三态终帧）；全量回归。

**完成证据**：（回填）

### WO-T3-2 ChatResult v2 与 blocks 投影

- 状态：`未完成`
- 对应设计：§6.2、§4.3（类型化结果）、§7.8.1
- 处置清单：`sentinel-engine/src/bdlh_runtime/api/projections.py`、`api/schemas.py`【修改】

**实施要求**：

1. `response.final` 载荷迁移为 ChatResult v2：`answer` / `blocks[]` / `tool_trace` / `evidence_refs` / `audit_codes` / `disclosures`；
2. `blocks` 由工具 Observation 的 `result_type` + `payload` **直接投影**，不经过 LLM 输出（设计文档 §4.3 展示真源约定）；
3. Block 类型枚举：`ScoreCard` / `AnalysisReport` / `SuitabilityDraft` / `PortfolioHealth` / `QuoteTable`；SuitabilityDraft 载荷遵守 C-2（匹配项与风险项成组、固定披露文案、无结论位）。

**验证方式**：契约测试覆盖五类 Block 投影与「数字与工具输出一致」断言（投影不篡改）。

**完成证据**：（回填）

### WO-T3-3 看护首页 dashboard

- 状态：`未完成`
- 对应设计：§7.1–§7.3、§7.6、§7.7
- 处置清单（均【新增】，另有两处【修改】）：

| 文件 | 处置 |
|---|---|
| `sentinel-console/public/dashboard.html`、`public/assets/dashboard.js`、`public/assets/dashboard.css` | 【新增】 |
| `sentinel-console/nginx.conf` | 【修改】（demo 档默认首页指向 dashboard） |
| `sentinel-console/public/index.html` | 【修改】（入口链接调整，先读后改） |

**实施要求**：

1. 布局、区域数据绑定、刷新策略、空态与降级严格按设计文档 §7.3 表格与 §7.7 状态表；
2. 图表使用 ECharts CDN（单 script 标签），不引入构建工具链；
3. 徽标组件（审计码 / 证据编号 / 演示注入水印 / 严重度色条）为全局复用组件，落 `public/assets/badges.js`【新增】；
4. SSE `notification` 事件实时 prepend 时间线；掉线回退 30s 轮询（§7.6）。

**验证方式**：`sentinel-console/test/dashboard-contract.test.js`【新增】契约测试通过；浏览器手动冒烟设计文档 §8 场景 #1–#3。

**完成证据**：（回填）

### WO-T3-4 追问抽屉与 Block 渲染器

- 状态：`未完成`
- 对应设计：§7.4、§7.8
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-console/public/assets/blocks.js` | 【新增】（渲染器注册表：`block.type → 组件`；未知类型降级折叠 JSON） |
| `sentinel-console/public/assets/chat.js` | 【修改】（`tool.step` 时间线、`response.final` v2 消费、追问上下文 chip；先读全文件再改） |

**实施要求**：

1. 追问抽屉自 P1 右滑出，顶部事件上下文 chip（`followup` 接口返回的事件摘要）；
2. `tool.step` 节点含工具名 / 参数摘要 / 耗时 / 结果态；`search_tools` 节点特殊渲染（检索词 + 命中数）；
3. Block 卡片位于回答文本之后、证据链卡之前；五类渲染按 §7.8.2–§7.8.5 线框；
4. 运行控制（暂停 / 恢复）与澄清选项卡按 §7.4。

**验证方式**：前端契约测试更新通过；手动冒烟 §8 场景 #4–#7。

**完成证据**：（回填）

### WO-T3-5 前端契约测试与对接文档重写

- 状态：`未完成`
- 对应设计：§11.1、文件树 §4
- 处置清单：`sentinel-console/test/frontend-contract.test.js`【修改】；`sentinel-console/CHAT_INTEGRATION.md`、`API_INTEGRATION.md`【修改】（按设计文档 §6.2 / §7 重写为新契约，删除「现行实现」状态头）。

**验证方式**：`npm test` 通过；文档与实现逐项一致（抽查三个事件与一个 Block 类型）。

**完成证据**：（回填）

---

## 5. 阶段 T4：收口

### WO-T4-1 一键演示 compose

- 状态：`未完成`
- 对应设计：§10 T4、§9
- 处置清单：`deploy/docker-compose.yml`【修改】（console 纳入演示拓扑、演示 seed 挂载）；`deploy/.env.example`【修改】（如需补充注释）。

**验证方式**：干净环境 `docker compose --env-file deploy/.env -f deploy/docker-compose.yml config -q` 通过；（具备 Docker 时）`up -d --build` 后 §8 场景 #1 可见。

**完成证据**：（回填）

### WO-T4-2 文档终稿同步

- 状态：`未完成`
- 对应设计：文件树 §5
- 处置清单：`README.md`【修改】（实施状态段）、`docs/architecture/00-Sentinel产品设计与架构.md`【修改】（变更记录追加一行；实施与设计的偏差项在对应章节脚注说明）。

**验证方式**：文档互链可用；无指向已删除文件 / 已改名目录的链接残留。

**完成证据**：（回填）

### WO-T4-3 演示彩排与录屏

- 状态：`未完成`
- 对应设计：§8
- 实施要求：设计文档 §8 七步剧本完整彩排 ≥3 遍并记录耗时与失败点；全流程录屏作为现场兜底；注入脚本参数化（标的 / 幅度可配）。

**验证方式**：七步全部通过；录屏文件归档（不入库）。

**完成证据**：（回填）

---

## 6. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-18 | 初版：按设计文档 §10 建立 T0–T4 共 23 张工单，全部 `未完成`；执行纪律与状态机生效 |
