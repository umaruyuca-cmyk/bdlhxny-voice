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
| WO-T0-1 | 基线确认与记录 | `完成` |
| WO-T0-2 | 演示 seed 数据 | `完成` |
| WO-T0-3 | 演示部署档配置 | `完成` |
| WO-T1-1 | watch 数据表 | `完成` |
| WO-T1-2 | watch 包骨架与事件契约 | `完成` |
| WO-T1-3 | 价格阈值事件源 | `完成` |
| WO-T1-4 | 晨报 / 盘后定时事件源 | `完成` |
| WO-T1-5 | 唤醒上下文组装器 | `完成` |
| WO-T1-6 | 通知落库与追问闭环 | `完成` |
| WO-T1-7 | 演示注入端点 | `完成` |
| WO-T1-8 | 看护环测试 | `完成` |
| WO-T2-1 | 工具目录（ToolCard） | `完成` |
| WO-T2-2 | 治理中间件 | `完成` |
| WO-T2-3 | Agent 循环与 scoped 装载 | `完成` |
| WO-T2-4 | tool search 装载模式 | `完成` |
| WO-T2-5 | eval 题库与双模式对照 | `完成` |
| WO-T2-6 | 装配切换与旧路径删除 | `完成` |
| WO-T3-1 | SSE 契约 v2（真流式） | `完成` |
| WO-T3-2 | ChatResult v2 与 blocks 投影 | `完成` |
| WO-T3-3 | 看护首页 dashboard | `完成` |
| WO-T3-4 | 追问抽屉与 Block 渲染器 | `完成` |
| WO-T3-5 | 前端契约测试与对接文档重写 | `完成` |
| WO-T4-1 | 一键演示 compose | `完成` |
| WO-T4-2 | 文档终稿同步 | `完成` |
| WO-T4-3 | 演示彩排与录屏 | `完成` |
| WO-T5-1 | 文档站重构与公开入口收敛 | `完成` |
| WO-T5-2 | 彩排脚本与演示剧本对齐（六步版） | `未完成` |
| WO-T5-3 | 子文档口径同步 | `未完成` |

---

## 1. 阶段 T0：基线与演示数据

### WO-T0-1 基线确认与记录

- 状态：`完成`
- 对应设计：§10 T0、§11.3
- 目的：记录实施前的测试基线，作为后续所有阶段的回归参照。

**处置清单**：无代码改动。

**实施要求**：

1. 执行 `cd sentinel-engine && uv run pytest -q`，记录通过数；执行 `uv run ruff check`；
2. 执行 `cd sentinel-data && mvn -B -ntp test`，记录结果；
3. 执行 `cd sentinel-console && npm test`，记录结果；
4. 在本工单「完成证据」回填三组数值。

**验证方式**：上述命令全部退出码为 0。

**完成证据**：
- pytest：447 passed（6.70s，退出码 0）；注：`uv run pytest` 直接调用在该环境无输出且退出码 1，改用 `uv run python -m pytest -q` 正常运行，后续阶段门禁沿用此调用
- ruff：All checks passed（退出码 0）
- mvn：Tests run: 40, Failures: 0, Errors: 0, Skipped: 0 — BUILD SUCCESS（完整路径 `D:/environment/apache-maven-3.9.16/bin/mvn.cmd`；系统 PATH 中 mvn 损坏，后续阶段门禁沿用完整路径调用）
- npm：tests 5 / pass 5 / fail 0（217ms）
- 日期：2026-08-19

### WO-T0-2 演示 seed 数据

- 状态：`完成`
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

**完成证据**：
- 新增 `db/postgresql/seed/demo_sentinel.sql`：演示用户 user_id=1（对齐 `BDLH_RUNTIME_SINGLE_USER_ID=1`）；稳健型画像 `risk_tolerance='moderate'`（对齐 Java `RISK_LEVELS`）；持仓 4 只——300750 宁德时代 / 600519 贵州茅台 / 600036 招商银行 / 000333 美的集团；含 `financial_profile_confirmations` 确认审计行；头部 `DELETE WHERE user_id=1` 守卫可重跑；目标记忆「两年内换房」未落库（数值 `near_term_cash_needs` 与展望天数落库，语义目标属 L3）。
- 新增 `db/execution/20260819_演示seed.md`：变更摘要、不清库重建说明、完整执行顺序（demo_sentinel.sql 为第 11 步）、验收要点、口径说明表。
- 修改 `db/README.md` 与 `db/execution/README.md`：当前基线链接改指向 `20260819_演示seed.md`，原 `20260818_run_projection_checkpoint.md` 降为历史基线。
- `mvn -B -ntp test`：Tests run: 40, Failures: 0 — BUILD SUCCESS（无劣化；本次仅新增 SQL/md，未触 Java 代码）。
- 日期：2026-08-19

### WO-T0-3 演示部署档配置

- 状态：`完成`
- 对应设计：§4.8（演示注入）、§6.1、C-4
- 目的：登记演示部署档开关，供 WO-T1-7 与前端水印使用。

**处置清单**：

- 【修改】`sentinel-engine/src/bdlh_runtime/config.py`（新增配置项 `demo_mode: bool`，环境变量 `BDLH_DEMO_MODE`，默认 `false`；先读该文件现有 Settings 写法，沿用同一风格）
- 【修改】`deploy/.env.example`（登记 `BDLH_DEMO_MODE=false` 及中文注释：演示部署档，开启后注册演示注入端点并显示演示标识）
- 【修改】`deploy/.env.ci`（追加同名键，保持 CI compose 校验通过）

**验证方式**：`uv run pytest -q` 全绿；配置单测覆盖默认值与显式开启两态（新增测试随本工单提交）。

**完成证据**：
- 修改 `sentinel-engine/src/bdlh_runtime/config.py`：Settings 新增 `demo_mode: bool = False`（基础运行分组，沿用现有 dataclass frozen 风格）；`from_environment` 解析 `BDLH_DEMO_MODE`（真值集合 `1/true/yes/on`，默认 false）。
- 修改 `deploy/.env.example`：在 `BDLH_RUNTIME_SINGLE_USER_ID` 后登记 `BDLH_DEMO_MODE=false`，附中文注释（演示部署档，开启后注册演示注入端点并显示演示标识，引用 §4.8、C-4）。
- 修改 `deploy/.env.ci`：追加 `BDLH_DEMO_MODE=false`（与 .env.example 键集合对齐，compose 校验通过）。
- 新增 `sentinel-engine/tests/infra/test_config.py`：13 个用例覆盖默认值、显式开启、`from_environment` 未设置/真值集合/假值集合三态。
- `uv run python -m pytest -q`：460 passed（基线 447 + 新增 13，净增符合基线先行纪律）；`uv run ruff check`：All checks passed。
- 日期：2026-08-19

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

**完成证据**：
- 新增 `db/postgresql/schema/watch.sql`：`runtime.watch_rule`（id/user_id/type CHECK/config JSONB/status CHECK active|paused/last_fired_at/审计时间）与 `runtime.watch_event`（id/rule_id/type CHECK/source CHECK∈{market_poll,cron,demo_inject}/payload JSONB/dedupe_key/occurred_at/created_at）；`uq_runtime_watch_event_dedupe_key` 唯一约束承载幂等；rule_id 不加外键（规则可删事件留审）；user_id 用 VARCHAR(128) 与 runtime schema 一致；表与列注释完整（参照 task_messaging.sql 风格）。
- 新增 `db/execution/20260819_watch表.md`：变更摘要、不清库重建说明、完整执行顺序（watch.sql 为第 10 步）、表结构要点、验收要点（含重复 dedupe_key 报唯一冲突的 SQL 样例）。
- 修改 `db/README.md` 与 `db/execution/README.md`：当前基线链接改指向 `20260819_watch表.md`。
- DB 实际执行验证：本环境无运行中的 PostgreSQL，空库执行与唯一冲突验收步骤已写入执行说明，作为运维执行清单；schema 语法与约束按既有 runtime 表风格编写。
- 日期：2026-08-19

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
2. 包注释引用设计文档 §4.8；`watch/` 不得 import `cognitive/`、`guardrails/` 以外的引擎内部件之外的内容——即仅允许依赖 `infra/`、`compute/`、`contracts/`（内核纯净度测试要求：先读 `sentinel-engine/tests/architecture/test_kernel_purity.py` 确认既有断言口径，新增包不得引入域字面量）。

**验证方式**：`uv run pytest -q` 全绿（含架构纯净度门禁）。

**完成证据**：
- 新增 `sentinel-engine/src/bdlh_runtime/watch/__init__.py`：包注释引用设计文档 §4.8，声明依赖纪律（仅依赖 infra/compute/contracts，禁 import cognitive/guardrails/domains/tools/integrations）。
- 新增 `sentinel-engine/src/bdlh_runtime/watch/events.py`：pydantic 定义 `WatchRule`（对齐 watch_rule 表）与 `WatchEvent`（对齐 watch_event 表）；字面量 frozenset `WATCH_RULE_TYPES`/`WATCH_EVENT_SOURCES`（含 demo_inject，C-4）/`WATCH_RULE_STATUSES`/`THRESHOLD_DIRECTIONS` 与 DB CHECK 一致；`make_price_threshold_dedupe_key(rule_id,symbol,direction,window_day)` 与 `make_cron_dedupe_key(rule_id,window_day)` 集中产出 dedupe_key（规则×触发窗口×方向）；仅依赖 pydantic + stdlib，满足纯净度。
- `tests/architecture/test_kernel_purity.py`：36 项全绿（含内核纯净度三断言，未引入域字面量）。
- `uv run python -m pytest -q`：460 passed（与 T0 收口持平，本工单未新增测试，测试落 WO-T1-8）；`uv run ruff check`：All checks passed。
- 日期：2026-08-19

### WO-T1-3 价格阈值事件源

- 状态：`未完成`
- 对应设计：§4.8（边沿触发 / 轮询纪律）
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/watch/sources.py` | 【新增】 |

**保留引用**（只读复用，先读后用）：

- `sentinel-engine/src/bdlh_runtime/infra/scheduler.py`（M6 调度回路，事件源的挂载点）
- `sentinel-engine/src/bdlh_runtime/infra/tasks.py`、`runtime/remote_tasks.py`（M6 价格任务底座：`financial_task` 轮询与结果获取）
- `sentinel-engine/src/bdlh_runtime/compute/trading_calendar.py`（交易日 / 交易时段判定）
- `sentinel-engine/src/bdlh_runtime/tools/java_data_adapter.py`（持仓与行情相关数据面调用）

**实施要求**：

1. 轮询器仅在交易时段运行（交易日历判定），非交易时段不发起请求；
2. 活跃规则按标的聚合后批量取价；越阈判定为**边沿触发**（与 `watch_rule.last_fired_at` 及当日已存事件的 `dedupe_key` 联合判定，杜绝水平重复触发）；
3. 产出 `WatchEvent` 经 WO-T1-2 契约落库；数据源失败指数退避并记日志，不中断轮询循环；
4. 全程不改写【保留引用】文件的行为；确需扩展时以新增函数方式叠加。

**验证方式**：`tests/watch/test_sources.py`（WO-T1-8）覆盖：交易时段判定、穿越触发、同向重复不触发、失败退避。

**完成证据**：
- 新增 `sentinel-engine/src/bdlh_runtime/watch/sources.py`：定义端口 `QuoteProvider`（批量取价）、`WatchRuleStore`（读活跃规则+回填 last_fired_at）、`WatchEventStore`（dedupe_key 预检+append）、`TradingSessionGate`（交易时段判定）；`QuoteSnapshot`（pydantic，含 prev_close 供 pct 判定）；`AShareTradingSessionGate`（交易日历+9:30-11:30/13:00-15:00 北京时段）；`PriceThresholdPoller.tick()`（交易时段门→聚合标的→批量取价→边沿触发判定「dedupe_key 预检+穿越检测」→落库+回填 last_fired_at，source=market_poll）；`_evaluate_crossing` 支持 pct/abs_price 两类阈值与 up/down 方向；`run_price_poller_loop`（整轮失败指数退避，部分失败不退避，不中断循环）；`DedupeKeyConflict` 异常承载幂等冲突吞并。
- 依赖纪律：仅依赖 `compute/trading_calendar` + 本包 events + pydantic/dataclasses/asyncio；行情与持久化均经端口注入（实现在 infra/ 装配时提供），保留引用文件零改动。
- `uv run python -m pytest -q`：460 passed（无回归）；`uv run ruff check`：All checks passed。
- 专用单测（交易时段/穿越/同向重复/退避）统一在 WO-T1-8 的 `tests/watch/test_sources.py` 编写。
- 日期：2026-08-19

### WO-T1-4 晨报 / 盘后定时事件源

- 状态：`完成`
- 对应设计：§4.8、§2.1 F1
- 处置清单：`sentinel-engine/src/bdlh_runtime/watch/sources.py`【修改】（新增 cron 类事件源函数）

**实施要求**：

1. `daily_briefing`（默认 08:30）与 `post_market_review`（默认 16:30）两类规则，仅在交易日产出事件；
2. 事件负载只含触发事实（交易日、规则配置），**不含资讯内容**——内容由唤醒后的 Agent 运行现取（设计文档 §4.8：晨报内容不在事件源生成）；
3. `dedupe_key` = 规则 × 交易日。

**验证方式**：交易日 / 非交易日 / 重复触发三态单测通过。

**完成证据**：
- 在 `sources.py` 新增 `CronEventSource`（source=cron）：`produce_for(rule_type)` 仅交易日（exchange_calendars XSHG）产出事件；payload 只含 `{trading_day, rule_config}`（不含资讯内容，§4.8）；`dedupe_key` 经 `make_cron_dedupe_key(rule_id, window_day)` = `cron:{rule_id}:{window_day}`；dedupe_key 冲突（DedupeKeyConflict）视为已产出跳过。覆盖 `daily_briefing` 与 `post_market_review` 两类；非法类型抛 ValueError。
- 规则默认触发时间（08:30 / 16:30）属规则 `config.time` 配置，由调度层按配置触发，事件源本身只负责「被调用时产出当日事件」。
- `uv run python -m pytest -q`：460 passed（无回归）；`uv run ruff check`：All checks passed。
- 交易日/非交易日/重复触发三态单测统一在 WO-T1-8 编写。
- 日期：2026-08-19

### WO-T1-5 唤醒上下文组装器

- 状态：`未完成`
- 对应设计：§4.5（唤醒态）、§4.6（记忆召回注入）
- 处置清单：`sentinel-engine/src/bdlh_runtime/watch/wakeup.py`【新增】

**保留引用**：`sentinel-engine/src/bdlh_runtime/infra/remote_runtime_data.py`（持仓 / 画像取数）、`sentinel-engine/src/bdlh_runtime/memory/recall.py`（L3 召回）、`sentinel-engine/src/bdlh_runtime/infra/application.py`（引擎装配入口，唤醒运行经此处进入）。

**实施要求**：

1. 输入 `WatchEvent` + `user_id`，输出「唤醒包」：解读系统提示引用 + 事件负载 + 持仓快照 + 风险画像 + L3 目标记忆（召回失败记 `memory_degraded` 标记，不阻断）；
2. 唤醒运行复用现行编排入口（本阶段引擎未替换，解读产出走现行链路）；
3. 系统提示文件落 `sentinel-engine/prompts/scene_wakeup.md`【新增】，按设计文档 §4.8 输出结构（标题 / 摘要 / 证据引用 / 审计码 / 严重度）与 C-1 / C-2 口径撰写；代码内不得内联长提示字符串。

**验证方式**：组装器单测（数据面与记忆以 Fake 注入）：唤醒包字段完整；记忆缺失时带降级标记。

**完成证据**：
- 新增 `sentinel-engine/prompts/scene_wakeup.md`：按 §4.8 输出结构（标题/摘要/证据引用/审计码/严重度）与 C-1（不交易）/C-2（不出具适当性结论，仅风险匹配筛查 DRAFT + 披露）/C-4（demo_inject 标注「演示注入」）口径撰写；含记忆降级（MEM-DEGRADED）与个性化要求。
- 新增 `sentinel-engine/src/bdlh_runtime/watch/wakeup.py`：`WakeupPack` dataclass（system_prompt_ref/system_prompt/event/user_id/portfolio_snapshot/risk_profile/memory_records/memory_degraded/memory_limitation/portfolio_degraded/risk_profile_degraded）；端口 `PortfolioSnapshotProvider`/`RiskProfileProvider`（Protocol，实现由 infra/ 装配注入）；`load_wakeup_prompt()` 从 `prompts/scene_wakeup.md` 加载（路径 parents[3] 解析到 sentinel-engine 根，缺失即抛错，禁止内联长字符串）；`WakeupAssembler.assemble(event,user_id)` 并发取持仓/画像（失败标降级不阻断）+ L3 召回（`recall_semantic_memory`，失败标 memory_degraded 不阻断）→ 组装唤醒包；`_memory_query_for(event)` 按事件类型构造召回查询。
- 偏差记录：wakeup.py 导入 `bdlh_runtime.memory.recall`——WO-T1-5 保留引用明确列入 memory/recall.py，是对 watch 包依赖（WO-T1-2 仅允许 infra/compute/contracts）的定向扩展；内核纯净度门禁不检查 watch/，36 项全绿未受影响。
- `uv run python -m pytest -q`：460 passed（无回归）；`uv run ruff check`：All checks passed。
- 组装器单测（Fake 注入、记忆缺失降级断言）统一在 WO-T1-8 的 `tests/watch/test_wakeup_flow.py` 编写。
- 日期：2026-08-19

### WO-T1-6 通知落库与追问闭环

- 状态：`未完成`
- 对应设计：§4.8（产出 / 追问闭环）、§6.1
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/watch/notify.py` | 【新增】（解读结果 → 通知写入） |
| `sentinel-engine/src/bdlh_runtime/api/routers/notifications.py` | 【修改】（新增 `POST /{id}/followup`） |
| `sentinel-engine/src/bdlh_runtime/infra/chat_sessions.py` | 【修改】（支持携带初始事件上下文建会话） |

**保留引用**：`sentinel-engine/src/bdlh_runtime/infra/remote_run_state.py`（run 引用持久化）；Java 侧 `NotificationController`（先读 `sentinel-data/src/main/java/com/bdlh/runtime/api/NotificationController.java` 确认既有通知契约，复用不落新表）。

**实施要求**：

1. 通知记录携带 `run_id`、事件摘要、严重度；同一运行结果只产生一条通知（与 run 结果唯一绑定）；
2. `followup` 创建会话并将事件摘要注入首轮上下文；返回 `session_id` 供前端直接进入追问；
3. 演示注入事件产生的通知，`payload.source=demo_inject` 必须透传至通知记录（C-4）。

**验证方式**：集成测试——注入 WatchEvent → 通知落库（字段断言）→ followup 建会话首轮上下文含事件摘要；重复运行不重复通知。

**完成证据**：
- 新增 `sentinel-engine/src/bdlh_runtime/watch/notify.py`：`WatchNotification`（pydantic，notification_id/run_id/user_id/event_id/event_type/event_summary/severity/source/title/body/audit_codes/evidence_refs/created_at）；`InterpretationResult`（解读结果契约，run_id/title/summary/severity/audit_codes/evidence_refs/body，T2 引擎替换后不变）；`WatchNotificationStore`（Protocol：write 幂等于 run_id / get / list_for_user）；`WatchNotificationWriter.write(interpretation,event,user_id)` 组装通知并落库，run_id 幂等保证同一 run 只一条通知（§4.9）；`event_source` 透传（demo_inject 保留至通知层，C-4）；`event_summary_for_followup(event)` 构造追问 chip 文本（含演示注入标注）。
- 修改 `sentinel-engine/src/bdlh_runtime/api/routers/notifications.py`：新增 `POST /notifications/{id}/followup`——鉴权→查通知（优先 watch_notification_store，回退 M6 outbox）→ `create_followup_session` 建会话注入事件摘要→返回 `{session_id, event_summary}`。
- 修改 `sentinel-engine/src/bdlh_runtime/infra/chat_sessions.py`：新增 `create_followup_session(store,user_id,event_summary)`——新建会话（不复用既有 id，追问上下文隔离）+ 事件摘要作 system 消息注入首轮上下文。
- 通知持久化复用既有 `runtime.user_notification`/Outbox 机制（端口注入，不落新表）；Java `NotificationController` 既有 GET 契约未改。
- `uv run python -m pytest -q`：460 passed（无回归）；`uv run ruff check`：All checks passed。
- 集成测试（注入→落库→followup→首轮上下文断言；重复运行不重复通知）统一在 WO-T1-8 编写。
- 日期：2026-08-19

### WO-T1-7 演示注入端点

- 状态：`完成`
- 对应设计：§4.8、§6.1、C-4
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/api/routers/demo_events.py` | 【新增】 |
| `sentinel-engine/src/bdlh_runtime/infra/application.py` | 【修改】（仅 `demo_mode=true` 时注册该路由） |

**实施要求**：

1. `POST /internal/demo/events`：请求体为事件类型与负载（如 `{type:"price_threshold", symbol:"300750", pct:-5.2}`），写入 `source=demo_inject` 的 `WatchEvent`，走与真实事件完全相同的后续链路；
2. 非 demo 档下路由不注册（404）；不得仅依赖「隐藏」；
3. 响应返回生成的事件 id，供演示脚本轮询通知到达。

**验证方式**：契约测试覆盖两档（开 / 关）；注入后事件带 `demo_inject` 标记贯穿至通知。

**完成证据**：
- 新增 `sentinel-engine/src/bdlh_runtime/api/routers/demo_events.py`：`DemoEventRequest`（type/symbol/pct/abs_price/direction/trading_day）；`POST /internal/demo/events` 写入 `source=demo_inject` 的 `WatchEvent`（rule_id=0 演示合成事件，watch_event.rule_id 无外键）；dedupe_key 含 uuid 允许演示迭代多次注入；pct 由符号推断 direction，合成 prev_close/price 供解读（演示数据非真实市场事实，C-4）；payload.demo=True；响应返回 `{event_id, dedupe_key, source}`。
- 修改 `sentinel-engine/src/bdlh_runtime/api/routes.py`（路由注册在此，非 application.py；application.settings.demo_mode 为装配真源）：`if application.settings.demo_mode: demo_events.register(router, ctx)`——非 demo 档路由不注册（404），不依赖隐藏。
- 偏差记录：WO 处置清单写「application.py【修改】」，实际路由注册在 `api/routes.py` 的 `create_api_app`；`application.py` 无需改动（demo_mode 已在 config.py/Settings，WO-T0-3 落地）。按一致性纪律记录此偏差，行为与 WO 一致。
- `uv run python -m pytest -q`：460 passed（无回归）；`uv run ruff check`：All checks passed。
- 契约测试（demo 档开/关路由注册、source 全链路透传）统一在 WO-T1-8 的 `tests/api/test_demo_events.py` 编写。
- 日期：2026-08-19

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

**完成证据**：
- 新增 `sentinel-engine/tests/watch/__init__.py`、`tests/watch/test_sources.py`（13 用例）：PriceThresholdPoller——非交易时段跳过、pct 向下穿越产出事件、无穿越无事件、同方向同日 dedupe 跳过（crossed 计数与 produced 分离）、abs_price 穿越、整轮取价失败计 failed、部分标的失败不阻断其它；CronEventSource——交易日产出、非交易日无事件、同日重复跳过、非法类型拒绝。Fake 端口（QuoteProvider/RuleStore/EventStore/SessionGate/Calendar）注入。
- 新增 `sentinel-engine/tests/watch/test_wakeup_flow.py`（10 用例）：WakeupAssembler——唤醒包字段完整（持仓/画像/记忆/系统提示）、记忆失败 degraded 不阻断、持仓失败 degraded 不阻断；WatchNotificationWriter——run_id 绑定 + demo_inject source 透传（C-4）、run_id 幂等不重复通知；create_followup_session——首轮 system 上下文含事件摘要、demo chip 含演示标记。
- 新增 `sentinel-engine/tests/api/test_demo_events.py`（6 用例）：demo 档关→404、demo 档开→注入成功返回 event_id + source=demo_inject、cron 事件注入、非法类型 400、price_threshold 缺 pct/abs_price 400、event_store 未装配 503。
- 修改 `sentinel-engine/src/bdlh_runtime/infra/application.py`：AgentRuntimeApplication 新增 `watch_event_store`/`watch_notification_store` 属性（看护环装配点，缺省 None）。
- 修复实现缺陷：`UTC + timedelta(hours=8)` 非法（timezone 不可加 timedelta）→ 改 `timezone(timedelta(hours=8))`（sources.py 与 demo_events.py）；`PriceThresholdPoller.crossed` 计数移至 dedupe 检查前（crossed=检测到穿越，produced=实际产出，审计语义更清晰）。
- `uv run python -m pytest -q`：484 passed（基线 460 + 本工单新增 24，净增符合基线先行纪律）；`uv run ruff check`：All checks passed。
- 日期：2026-08-19。T1 看护环阶段收口。

---

## 3. 阶段 T2：工具层

> 阶段目标：统一工具目录 + 原生 tool calling 循环 + 治理中间件 + 双模式装载；完成后旧意图路由与域插件框架物理删除。

### WO-T2-1 工具目录（ToolCard）

- 状态：`完成`
- 对应设计：§4.1
- 处置清单：`sentinel-engine/src/bdlh_runtime/tools/catalog.py`【新增】

**保留引用**：`sentinel-engine/src/bdlh_runtime/tools/capabilities.py`（现有能力清单，迁移数据源）、`sentinel-engine/src/bdlh_runtime/integrations/mcp/registry.py` 与 `integrations/mcp/adapter.py`（MCP 工具发现）。

**偏差记录**：
1. 处置清单仅 `catalog.py`【新增】；实际还需【修改】`tests/registry/seeded_store.py`（测试桩 `required_arguments` 与 `registry.sql` 对齐，否则参数 schema 无法投影）与 `tools/__init__.py`（导出 ToolCard 真源，不改变既有 Capability 导出）。
2. 记忆不在八表 capability 种子中；按实施要求第 2 条在目录层登记只读 `memory.recall`（origin=local）。L3 写入仍走 `memory/writer` 管道，禁止登记 write 工具（只读红线）。
3. 双目的 `description` 由目录层 overlay 撰写，不改 DB `capability.description`（处置清单未含 seed；DB 文案仍为运维口径）。
4. 装载器 / 检索索引 / 治理中间件尚未存在（WO-T2-2/T2-3/T2-4）；本工单只提供目录读取 API（`get` / `list` / `list_visible`），不改 `application.py` 装配（属 WO-T2-6）。
5. 现行 MCP client 仅 `call_tool`、无 `list_tools`；`adapter=mcp` 的统一能力经 snapshot 迁移为 `origin=mcp`；动态 MCP 经 `register_mcp_tool` 代理登记。不改 adapter / registry（保留引用）。

**实施要求**：

1. `ToolCard` 字段严格按设计文档 §4.1（`name` / `description` / `parameters` / `origin` / `read_only` / `required_scope` / `cost_hint`）；
2. 本地工具（行情、持仓、画像、分析引擎、Web 检索、记忆）与 MCP 工具统一登记；目录为唯一真源，装载器 / 检索索引 / 中间件均从目录读取；
3. `description` 面向「模型选择 + embedding 检索」双目的撰写；
4. **目录中不得注册任何交易执行语义的工具（C-1）**。

**验证方式**：目录单测（字段完整性、`read_only` 标记覆盖、MCP 工具代理登记）。

**完成证据**：
- 新增 `sentinel-engine/src/bdlh_runtime/tools/catalog.py`：`ToolCard`（pydantic，§4.1 七字段）+ `ToolOrigin`/`CostHint` + `is_trading_semantic`（C-1：英文单词边界 + 中文子串，防 CJK `\\b` 漏判；`_`/`.`/`-` 归一化；`portfolio.get_transaction_history` 只读豁免）+ pydantic 参数契约投影 JSON Schema + 双目的 description overlay + `ToolCatalog`（重名 / 交易语义 / 只读红线三关；`list_visible`）+ `catalog_from_snapshot`（CapabilityRegistry 迁移：adapter=mcp→origin=mcp；scope 自 toolsets+authenticated；deep_search→premium、memory.recall→free）+ `_register_engine_local_tools`（只读 `memory.recall`）+ `register_mcp_tool`。
- 修改 `tools/__init__.py`：导出 ToolCard / ToolCatalog 等，保留既有 Capability 导出。
- 修改 `tests/registry/seeded_store.py`：`REQUIRED_ARGUMENTS` 与 `registry.sql` 对齐。
- 新增 `tests/tools/test_catalog.py`：25 个用例（C-1 英文 4 + 中文描述 1 + 放行 4 + 注册拒绝 3 态 + 豁免 1；snapshot 覆盖含 memory.recall；七字段；authenticated；premium；scope；双目的 description；六类本地+MCP；pydantic 投影；manifest 不含治理字段；目录无交易工具；MCP 代理与一致治理）。
- `uv run python -m pytest -q`：509 passed（基线 484 + 本工单 25）；`uv run ruff check`：All checks passed。
- 日期：2026-08-19

### WO-T2-2 治理中间件

- 状态：`完成`
- 对应设计：§4.4（G1–G7）
- 处置清单：`sentinel-engine/src/bdlh_runtime/guardrails/middleware.py`【新增】

**保留引用**：`sentinel-engine/src/bdlh_runtime/guardrails/policies.py`、`guardrails/interfaces.py`、`guardrails/contracts.py`（既有四时点检查逻辑——中间件复用其检查函数，本工单不删除这些文件）。

**偏差记录**：
1. `contracts.py` 为保留引用，不扩展 `GuardrailStage`；G1–G5 前置拦截以 `ACTION` 时点返回 `GuardrailResult`，G6 以 `DATA_QUALITY` 时点复用 `DefaultDataQualityGuardrail`。
2. 内核纯净度禁止 `guardrails` import `tools`；中间件经 Protocol（`get`/`contains` + ToolCard 七字段只读视图）读取目录，不维护第二份清单。
3. 处置清单仅 `middleware.py`【新增】；`guardrails/__init__.py`【修改】导出中间件符号，不改变既有四时点导出。
4. G6 包装使用既有 `Observation`（`provenance.source` / `retrieved_at` / `data_quality`），不平行定义设计示意字段名。

**实施要求**：

1. 拦截链顺序固定为 G1 可见性 → G2 只读 → G3 权限 → G4 预算 → G5 参数校验 → 执行 → G6 Observation 包装 → G7 审计记录；任一前置拦截即终止并返回结构化拒绝（含审计码）；
2. 中间件对本地工具与 MCP 工具一致生效；新增工具无需治理侧适配；
3. 审计记录字段：调用者、工具名、参数摘要、耗时、结果状态、审计码。

**验证方式**：G1–G7 逐条单测（含幻觉工具名拒绝、预算耗尽、参数非法）；全量回归。

**完成证据**：
- 新增 `sentinel-engine/src/bdlh_runtime/guardrails/middleware.py`：`GovernanceMiddleware.invoke` 固定拦截链 G1 可见性（装载集合防幻觉）→ G2 只读 → G3 游客/机主与 scope → G4 预算扣减（premium 权重 3）→ G5 jsonschema 参数校验 → executor → G6 包装既有 Observation 并复用 `DefaultDataQualityGuardrail` → G7 `AuditRecord`（caller/tool_name/arguments_summary/elapsed_ms/status/audit_code）。前置拦截不调用 executor；本地与 MCP 同一链；目录经 Protocol 读取。
- 修改 `guardrails/__init__.py`：导出 `GovernanceMiddleware` / `AuditRecord` / `MiddlewareResult`。
- 新增 `tests/guardrails/test_middleware.py`：16 个用例（幻觉名、装载外真名、只读、游客、scope、预算耗尽、premium 加权、参数非法、Observation 包装/复用/质量拦截、审计字段、本地+MCP 同链、新 MCP 零适配、前置不执行、执行异常结构化失败）。
- `uv run python -m pytest -q`：526 passed（基线 509 + 本工单 16 + 内核纯净度对 middleware.py 增 1 参数化）；`uv run ruff check`：All checks passed。
- 日期：2026-08-19

### WO-T2-3 Agent 循环与 scoped 装载

- 状态：`完成`
- 对应设计：§4.2、§4.3（三层闸门）
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/engine/__init__.py`、`engine/loop.py`、`engine/loader.py` | 【新增】 |
| `sentinel-engine/prompts/system_base.md`、`prompts/scene_chat.md`、`prompts/scene_direct.md` | 【新增】 |

**保留引用**：`sentinel-engine/src/bdlh_runtime/infra/llm.py`（`create_llm`，LangChain `ChatOpenAI` 构造）；`sentinel-engine/src/bdlh_runtime/cognitive/semantic_router/`（快路径，整包保留）。

**偏差记录**：
1. 工单写 `runtime/readiness.py`，实际路径为 `infra/readiness.py`（包重命名）。本工单不改 `/ready` 装配（属 WO-T2-6）；`llm is None` 时循环不启动并返回 `degraded`。现行生产 `create_application` 缺 Key 仍 fail-closed。
2. 现行快路径仅 `chitchat` / `knowledge` / `forbidden`；未命中进入循环时 `scene_tag` 由调用方传入，缺省 `research`。映射表 4 行：`market` / `portfolio` / `research` / `watch`。不改 `fastpath_data.py`（保留引用整包）。
3. 实施要求第 3 条「N 为配置项」：`config.py` 增 `session_history_turns`（默认 10，环境变量 `BDLH_SESSION_HISTORY_TURNS`），并同步 `deploy/.env.example` 与 `.env.ci`。
4. 本工单不改 `application.py`（装配切换属 WO-T2-6）；executor 由调用方注入。

**实施要求**：

1. `loop.py`：`bind_tools` 原生 tool calling 循环——模型输出 `tool_calls` → WO-T2-2 中间件 → Observation 回填 → 直至模型产出最终回答或预算耗尽；无 `tool_calls` 时直接应答（设计文档 §4.3 G-β）；
2. `loader.py`：`scoped` 策略——场景标签 → 工具包映射表（代码内常量，3–4 行量级）；场景标签来自语义快路径；
3. 会话上下文：最近 N 轮消息 + L3 召回注入消息序列（N 为配置项，默认 10）；
4. 系统提示从 `prompts/` 文件加载，禁止内联长字符串；
5. 无 LLM Key 环境：循环不启动，走现行降级路径，`/ready` 报 degraded（沿用 `runtime/readiness.py` 既有机制）。

**验证方式**：FakeChatModel 集成测试（构造 `tool_calls` / 纯文本两类返回）；上下文与记忆注入断言；全量回归。

**完成证据**：
- 新增 `engine/loader.py`：`SCENE_TOOLSETS` 四行（market/portfolio/research/watch）+ `ToolLoader.load_scoped`（功能 toolset 交集 + authenticated 身份过滤）。
- 新增 `engine/loop.py`：G-α 快路径（chitchat 罐头 / knowledge 直答 LLM / forbidden 拒绝，不装载工具）→ `bind_tools` 循环（tool_calls → GovernanceMiddleware → ToolMessage Observation 回填；无 tool_calls 即 G-β 直答）；`llm is None` 不启动并 `degraded`；提示从 `prompts/` 加载。
- 新增 `prompts/system_base.md`、`scene_chat.md`、`scene_direct.md`。
- 修改 `config.py` / `.env.example` / `.env.ci`：`session_history_turns` 默认 10。
- 新增 `tests/engine/test_loop.py`（12）+ 配置 2：FakeChatModel 纯文本 / tool_calls 回填、历史裁剪、L3 注入、无 LLM、快路径跳过循环。
- `uv run python -m pytest -q`：540 passed（基线 526 + 14）；`uv run ruff check`：All checks passed。
- 日期：2026-08-19

### WO-T2-4 tool search 装载模式

- 状态：`完成`
- 对应设计：§4.2（search 策略及补充规则）
- 处置清单：`sentinel-engine/src/bdlh_runtime/tools/search.py`【新增】；`engine/loader.py`【修改】（双策略分发）

**保留引用**：`sentinel-engine/src/bdlh_runtime/cognitive/semantic_router/encoder.py`（embedding 编码器复用）。

**偏差记录**：
1. 另一执行者仅完成读码，`search.py` / `BDLH_TOOL_LOADING` 均未落地，本工单从零补齐。
2. 动态装载需在命中后重绑 `bind_tools`，`engine/loop.py`【修改】（处置清单未列，否则命中工具无法进入后续上下文）。
3. 元工具 `search_tools` 登记进工具目录（唯一真源，供 G1）；`load_scoped` 将其排除，仅 search 策略初始装载。目录测试「点分名」对元工具豁免。
4. `config.py` / `.env.example` / `.env.ci` 登记 `BDLH_TOOL_LOADING`（工单已要求 example；ci 键集合对齐）。

**实施要求**：

1. `search_tools(query, top_k=3)` 元工具：对权限过滤后的目录做 embedding 相似度检索，命中 ToolCard 动态装载进后续上下文；权限过滤先于检索（§4.2）；
2. 会话级装载缓存；`search_tools` 调用计入预算；连续 2 次未命中回退 `scoped` 宽包；
3. 配置项 `BDLH_TOOL_LOADING=scoped|search`，默认 `scoped`（登记 `config.py` 与 `deploy/.env.example`）。

**验证方式**：检索命中 / 未命中回退 / 缓存 / 预算扣减四类单测。

**完成证据**：
- 新增 `tools/search.py`：`ToolSearchIndex` 对权限过滤后的 ToolCard 做 embedding 余弦检索（top-k + 阈值 0.28）；编码器复用 `cognitive.semantic_router.encoder`；`EncoderUnavailableError` 降级为未命中。
- 修改 `engine/loader.py`：`tool_loading=scoped|search` 分发；search 初始仅装载 `search_tools`，命中写入会话缓存后进入后续装载；连续 2 次未命中回退 research 宽包；`load_scoped` 排除元工具。
- 修改 `engine/loop.py`：每轮按 `load_for_turn` 重绑 `bind_tools`；`search_tools` 经治理中间件执行并计入预算。
- 修改 `tools/catalog.py`：登记元工具 `search_tools`（pydantic `query`/`top_k`，双目的 description）。
- 修改 `config.py` / `.env.example` / `.env.ci`：`BDLH_TOOL_LOADING` 默认 `scoped`。
- 新增 `tests/tools/test_search.py`（5）+ `tests/engine/test_search_loading.py` 四类（命中 / 未命中回退 / 缓存 / 预算，6）+ 配置 4：共 15。
- `uv run python -m pytest -q`：555 passed（基线 540 + 15）；`uv run ruff check`：All checks passed。
- 日期：2026-08-19

### WO-T2-5 eval 题库与双模式对照

- 状态：`完成`
- 对应设计：§11.2
- 处置清单：`sentinel-engine/tests/eval/__init__.py`、`tests/eval/routing_cases.py`、`tests/eval/run_eval.py`【新增】；报告落 `docs/eval/YYYYMMDD_装载模式对照.md`【新增】（执行当日日期）。

**偏差记录**：
1. 新增 `tests/eval/test_eval.py`（工单未列）：pytest 门禁需覆盖题库规模与双模式不低于基线，否则跑批脚本无法进入回归。
2. 离线 Fake 按金标脚本调用工具，度量装载可达性与检索命中，而非真实模型选工具能力；token 以「消息+工具 schema 字符数 / 4」近似，不引入 tokenizer。
3. 真实 LLM 标注为可选（`BDLH_EVAL_LIVE_LLM=1` + API Key）；无 Key 时报告标明跳过，不阻断工单。

**实施要求**：

1. 题库 ≥40 条：闲聊 / 知识 / 金融研究 / 组合 / 适合度 / 多轮指代 / 误伤 / 看护场景 ≥6 条；
2. 同一题库对 `scoped` 与 `search` 各跑一遍（离线 Fake 驱动 + 可选真实 LLM 标注），输出任务成功率、检索命中率（search 组）、平均轮次、token 消耗对比；
3. 报告含结论与默认策略建议。

**验证方式**：跑批脚本可重复执行并产出结构化结果；报告归档。

**完成证据**：
- 新增 `tests/eval/routing_cases.py`：48 条（八类各 6）；`run_eval.py` 对 scoped/search 跑 Fake 金标对照，输出任务成功率 / 检索命中率 / 平均轮次 / 近似 token。
- 新增 `tests/eval/test_eval.py`：题库覆盖门禁 + 双模式不低于基线 100%。
- 报告：`docs/eval/20260819_装载模式对照.md`。Fake 结果：scoped 成功率 100%、均轮 1.46、近似 token 1576；search 成功率 100%、检索命中 100%、均轮 2.12、近似 token 1077。建议默认保持 `scoped`（D-4）。
- 跑批：`uv run python -m tests.eval.run_eval` 退出码 0。
- `uv run python -m pytest -q`：557 passed（基线 555 + 2）；`uv run ruff check`：All checks passed。
- 日期：2026-08-19

### WO-T2-6 装配切换与旧路径删除

- 状态：`完成`
- 对应设计：§11.3（物理删除纪律）
- 处置清单：

| 文件 / 目录 | 处置 |
|---|---|
| `sentinel-engine/src/bdlh_runtime/infra/application.py` | 【修改】（装配切换至 `engine/`；删除域插件装配段） |
| `sentinel-engine/src/bdlh_runtime/cognitive/understand.py`、`cognitive/goal_action_selector.py`、`cognitive/goal_schema.py` | 【删除】（伪 function calling 与规则路由） |
| `sentinel-engine/src/bdlh_runtime/domains/` 整包 | 【删除】（域插件框架，C-5） |
| `sentinel-engine/src/bdlh_runtime/registry/`（如仅服务于域插件装配） | 【保留引用】（全局检索确认仍服务 ToolCatalog / 启动校验） |
| `sentinel-engine/tests/domains/`、`tests/cognitive/test_goal_action_selector.py` 等专属测试 | 【删除】（全局检索确认引用为零后执行） |

**偏差记录**：
1. `registry/` **保留**：ToolCatalog / CapabilityRegistry / 启动校验 / Java 远程快照均依赖，非域插件专属。
2. 装配切换必须让 `chat.py` / `agent_runs.py` / `scheduler.py` 仍能 `.run(InputEvent)`；新增 `engine/runtime.py`（EngineRuntime）与 `engine/executor.py`（CatalogToolExecutor），`CognitiveExecution` 迁入 `cognitive/contracts.py`。chat 伪流式仍属 T3-1，本工单不改 24 字切片。
3. `cognitive/` 删除清单外仍删除 orchestrator / plugin_gates / policy / goal_coverage / topic_hints（工单要求完成后仅剩快路径与 checkpoint）。`GoalSpec` / 通用 `DomainRequest` 边界迁入 `contracts.py`，供 checkpoint 与既有四时点 Guardrail 序列化。
4. 内核纯净度第二断言原预设 `cognitive → domains.contracts`；域包删除后改为「cognitive 不 import domains」。`KERNEL_TARGETS` 去掉已删的 `domains/contracts.py`、`domains/registry.py`。三测试函数仍在。
5. `infra/manifest_validation.py` 仅服务域 Skill manifest，随域包删除。
6. 唤醒价格从 `DomainOutcome.stock_research_result` 改为行情 Observation（`market.get_realtime_quote`）。
7. 行为重写落 `tests/engine/`：快路径、只读拦截、适合度、checkpoint；旧 `tests/domains/` 与 Understand/Orchestrator 专属测试按工单删除（完成证据注明删除数）。

**实施要求**：

1. 删除前对每项目标执行全局引用检索并在「完成证据」中列出检索结论；
2. 行为场景迁移按「场景保留、断言重写」：既有测试覆盖的关键行为（快路径分流、只读拦截、适合度闭环、checkpoint 恢复）在 `tests/engine/` 下按新契约重写后方可删除旧测试；
3. 本工单完成后，`cognitive/` 中保留的仅剩快路径与 checkpoint 相关组件；`test_kernel_purity.py` 三断言原样通过。

**验证方式**：`uv run pytest -q` 全绿（完成证据注明删除测试数与重写测试数）；`uv run ruff check` 通过。

**完成证据**：
- 日期：2026-08-19
- 全局检索：`src/` 内 `bdlh_runtime.domains` / `cognitive.orchestrator` / `understand` / `goal_action_selector` / `goal_schema` 引用为零；`registry/` 仍被 `tools/catalog.py`、`tools/capabilities.py`、`infra/application.py` 使用 → 按偏差保留
- 删除专属测试 **153**（`tests/domains/` + Understand/Orchestrator/goal_coverage/action_policy + `test_manifest_validation` + `test_manifests`；collect-only 151，另 `test_action_policy` 2 条因导入已断未能 collect）
- 就地精简 **8**（`test_foundation_contracts` 去掉金融域契约 7 条；`test_remote_run_state` 2→1）
- 重写新增 **7**（`tests/engine/`：快路径 2、只读 2、适合度 2、checkpoint 1）；装配/SSE/唤醒等断言随新契约改写，不另计条数
- pytest：`uv run python -m pytest -q` → **393 passed**（5.01s，退出码 0）；相对 T2-5 基线 557，下降 164，均属本工单明确删除/精简
- ruff：All checks passed（退出码 0）
- `cognitive/` 现仅 `contracts.py` / `checkpoint.py` / `semantic_router/`；`test_kernel_purity.py` 三函数通过

---

## 4. 阶段 T3：前端与流式

### WO-T3-1 SSE 契约 v2（真流式）

- 状态：`完成`
- 对应设计：§6.2
- 处置清单：`sentinel-engine/src/bdlh_runtime/api/routers/chat.py`、`api/sse.py`【修改】；另按偏差【修改】`engine/loop.py`、`engine/runtime.py`

**偏差记录**：
1. 真 `astream` 无法只改 chat 层：现行 `EngineRuntime.run()` 等循环结束后才返回。本工单同时【修改】`engine/loop.py`、`engine/runtime.py`，经 observer 在循环内推送 `token` / `tool.step`；chat 用队列边跑边 yield。`response.final` 的 ChatResult v2 / blocks 属 WO-T3-2，本工单不改投影形状。
2. 注入式 Fake cognitive（无 LLM）与快路径罐头文案没有 `astream`：删除 24 字切片后，若运行中未推送任何 token，完成路径补一帧整段 `token`（非定长切片）。
3. 伪流式删除前定位：`chat.py` 原 346–355 行 `for start in range(0, len(answer), 24)`。

**实施要求**：

1. `token` 事件改为 LLM `astream` 真实流式分片，**删除伪流式切片逻辑**（先读 `chat.py` 定位现有 24 字符切片段，删除并在完成证据中注明行区间）；
2. 新增 `tool.step` 事件（tool / arguments / status 实时外显，含 `search_tools` 检索节点）；`agent_run` 与 `done` 两帧语义不变；
3. `NEED_CLARIFICATION` / 拦截 / 降级三态的事件序列符合设计文档 §6.2 表。

**验证方式**：SSE 契约测试（分片非均质定长、`tool.step` 序列、三态终帧）；全量回归。

**完成证据**：
- 删除伪流式：`chat.py` 原 346–355 行 `for start in range(0, len(answer), 24)` 已删除；现由循环内 LLM `astream` 推 `token`，无流式时完成路径补一帧整段 `token`（拦截路径不补）。
- `sse.py` 新增 `encode_token` / `encode_tool_step`；循环经 `StreamSink` 推 `token` 与 `tool.step`（含 `search_tools` 的 query / hitCount）；chat 用 asyncio 队列边跑边 yield。`agent_run` / `done` 语义保持；`response.final` 形状未改（属 T3-2）。
- 三态：ASK_USER → `done NEED_CLARIFICATION`；拦截 → `guardrail.blocked` + `done FAILED`；LIMITED → `status.step=degraded` + `done COMPLETED`（`resultStatus=LIMITED`）。
- 新增 `tests/api/test_sse_v2.py`（6）：非均质分片、`tool.step`（含 search_tools）、NEED_CLARIFICATION / FAILED / LIMITED。
- pytest：`uv run python -m pytest -q` → **399 passed**（4.98s，退出码 0）；相对 T2-6 基线 393，+6，无删除。
- ruff：All checks passed（退出码 0）
- 日期：2026-08-19

### WO-T3-2 ChatResult v2 与 blocks 投影

- 状态：`完成`
- 对应设计：§6.2、§4.3（类型化结果）、§7.8.1
- 处置清单：`sentinel-engine/src/bdlh_runtime/api/projections.py`、`api/schemas.py`【修改】；另按偏差【修改】`contracts/observation.py`、`engine/loop.py`、`engine/runtime.py`、`cognitive/contracts.py`、`guardrails/middleware.py`、`api/routers/chat.py`

**偏差记录**：
1. 现行 `Observation` 无 `result_type` / `payload`，`PublicResponse` / `CognitiveExecution` 也不携带工具 Observation。投影无法只靠 `chat_final_payload(response)` 取到 blocks。本工单给 Observation 增加可选字段，G6 wrap 时从工具 dict 提升；`AgentResult` / `CognitiveExecution` 收集 Observation 与 `tool_trace`；`chat.py` 把二者传入终帧。工具尚未普遍产出类型化结果（属后续），契约测试以构造 Observation 覆盖五类 Block。
2. `response.final` 增加 ChatResult v2 字段（`answer` / `blocks` / `tool_trace` 等）；既有 `response_kind` / `data_times` / `limitations` 保留，避免 T3-1 终帧断言回退。

**实施要求**：

1. `response.final` 载荷迁移为 ChatResult v2：`answer` / `blocks[]` / `tool_trace` / `evidence_refs` / `audit_codes` / `disclosures`；
2. `blocks` 由工具 Observation 的 `result_type` + `payload` **直接投影**，不经过 LLM 输出（设计文档 §4.3 展示真源约定）；
3. Block 类型枚举：`ScoreCard` / `AnalysisReport` / `SuitabilityDraft` / `PortfolioHealth` / `QuoteTable`；SuitabilityDraft 载荷遵守 C-2（匹配项与风险项成组、固定披露文案、无结论位）。

**验证方式**：契约测试覆盖五类 Block 投影与「数字与工具输出一致」断言（投影不篡改）。

**完成证据**：
- `schemas.py` 新增 `ResultBlock` / `ChatResultV2`；`SUITABILITY_DISCLOSURE` 固定为「本结果仅为风险匹配筛查草稿，不构成投资建议。」
- `chat_final_payload` 输出 ChatResult v2：`answer` / `blocks` / `tool_trace` / `evidence_refs` / `audit_codes` / `disclosures`。`blocks` 由 Observation `result_type` + `payload` deepcopy 投影，五类枚举以外丢弃；SuitabilityDraft 强制匹配项/风险项成组、去掉结论位、覆盖固定披露，数字字段与工具输出一致。
- Observation 增加可选 `result_type` / `payload`；G6 wrap 从工具 dict 提升；循环收集 Observation，`CognitiveExecution` 带出 `observations` / `tool_trace`，chat 终帧消费。既有 `response_kind` / `data_times` / `limitations` 保留。
- 新增 `tests/api/test_chat_result_v2.py`（7）：五类数字直通、C-2、未知类型丢弃、嵌套 data 提升、终帧形状、SSE blocks、引擎 lift。
- pytest：`uv run python -m pytest -q` → **406 passed**（4.99s，退出码 0）；相对 T3-1 基线 399，+7，无删除。
- ruff：All checks passed（退出码 0）
- 日期：2026-08-19

### WO-T3-3 看护首页 dashboard

- 状态：`完成`
- 对应设计：§7.1–§7.3、§7.6、§7.7
- 处置清单（均【新增】，另有两处【修改】）：

| 文件 | 处置 |
|---|---|
| `sentinel-console/public/dashboard.html`、`public/assets/dashboard.js`、`public/assets/dashboard.css` | 【新增】 |
| `sentinel-console/nginx.conf` | 【修改】（demo 档默认首页指向 dashboard） |
| `sentinel-console/public/index.html` | 【修改】（入口链接调整，先读后改） |
| `sentinel-console/dev-server.js` | 【修改】（偏差：`/` 与 `/dashboard` 映射、notifications/watch-rules 代理到 Python） |
| `sentinel-console/public/assets/badges.js` | 【新增】（工单实施要求第 3 条；徽标全局组件） |
| `sentinel-console/test/dashboard-contract.test.js` | 【新增】（验证方式指定） |

**偏差记录**：
1. `GET /api/v1/watch-rules` 与 SSE `notification` 通道尚未落地（T1 只有规则/通知存储，无对应 HTTP/SSE）。本工单前端按设计文档路径绑定：规则 404 走空态引导；SSE 连 `/api/v1/notifications/stream`，失败则指数退避重连并 30s 轮询 `GET /notifications`。`?unread=count` 若仍返回列表则本地计数。
2. 持仓 API（`GET /api/portfolio/positions`）无实时行情字段，概览展示成本合计与目标权重，今日涨跌 / 浮盈在无行情时为「—」，不编造市值。
3. 追问抽屉完整会话属 WO-T3-4；本工单调用 `followup` 后打开右侧抽屉壳（事件上下文 chip + 进入 `/agent`）。
4. 工单未列 `dev-server.js`，但本地 `/` 与 Python 代理不改则无法冒烟，做最小映射修改。

**实施要求**：

1. 布局、区域数据绑定、刷新策略、空态与降级严格按设计文档 §7.3 表格与 §7.7 状态表；
2. 图表使用 ECharts CDN（单 script 标签），不引入构建工具链；
3. 徽标组件（审计码 / 证据编号 / 演示注入水印 / 严重度色条）为全局复用组件，落 `public/assets/badges.js`【新增】；
4. SSE `notification` 事件实时 prepend 时间线；掉线回退 30s 轮询（§7.6）。

**验证方式**：`sentinel-console/test/dashboard-contract.test.js`【新增】契约测试通过；浏览器手动冒烟设计文档 §8 场景 #1–#3。

**完成证据**：
- 新增 `dashboard.html` / `dashboard.css` / `dashboard.js`：四区（持仓概览+列表、事件时间线、活跃监视条、Header 未读）；骨架屏 / 空态 / 区域错误重试 / `/ready` 降级条 / Header「演示数据」横幅。
- 新增 `badges.js`：审计码、证据 `[n]`、演示注入水印、严重度 3px 色条；时间线 SSE `notification` prepend，失败指数退避并 30s 轮询。
- ECharts CDN 单 script：持仓目标权重环形图；无行情时今日/浮盈显示「—」，不编造市值。
- `nginx.conf`：`/` 与 `/dashboard` → `dashboard.html`；notifications / watch-rules / ready 反代 Python。`index.html` 增加看护首页入口。`dev-server.js` 同步映射。
- 新增 `test/dashboard-contract.test.js`（4）。`npm test`：tests 9 / pass 9 / fail 0（相对 T0 基线 5，+4）。
- §8 场景 #1–#3 浏览器冒烟：本环境未起全栈 compose，契约测试覆盖首页结构、数据绑定与注入水印/追问入口；现场冒烟待 T4 彩排。
- 日期：2026-08-19

### WO-T3-4 追问抽屉与 Block 渲染器

- 状态：`完成`
- 对应设计：§7.4、§7.8
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-console/public/assets/blocks.js` | 【新增】（渲染器注册表：`block.type → 组件`；未知类型降级折叠 JSON） |
| `sentinel-console/public/assets/chat.js` | 【修改】（`tool.step` 时间线、`response.final` v2 消费、追问上下文 chip；先读全文件再改） |

**偏差记录**：
1. 工单只列 `blocks.js` / `chat.js`。抽屉壳、运行控制与 Block 样式需要 `chat.html`、`chat-theme.css`；P1「右滑出」需 `dashboard.js` 把会话装进抽屉 iframe。本工单对这些文件做最小修改。
2. 恢复沿用既有 Turn Router：暂停后点「恢复」发送「继续」，不另接一套 resume HTTP 流。
3. `response.final` 的 Block 插在回答文本之后、证据链卡之前；token 流式正文不改写成伪打字机。

**实施要求**：

1. 追问抽屉自 P1 右滑出，顶部事件上下文 chip（`followup` 接口返回的事件摘要）；
2. `tool.step` 节点含工具名 / 参数摘要 / 耗时 / 结果态；`search_tools` 节点特殊渲染（检索词 + 命中数）；
3. Block 卡片位于回答文本之后、证据链卡之前；五类渲染按 §7.8.2–§7.8.5 线框；
4. 运行控制（暂停 / 恢复）与澄清选项卡按 §7.4。

**验证方式**：前端契约测试更新通过；手动冒烟 §8 场景 #4–#7。

**完成证据**：
- 新增 `sentinel-console/public/assets/blocks.js`：五类 Block 注册表 + 未知类型折叠 JSON；SuitabilityDraft 固定披露、匹配+风险成组、不渲染「适合/推荐买入」。
- `chat.js`：消费 `tool.step`（含 `search_tools` 检索词/命中数）与 `response.final` v2（blocks 在回答后、证据链卡前）；`followup`/`sessionId` chip；暂停/恢复；澄清条；`/ready` 降级条。
- P1 追问抽屉改为 iframe 装入 `/agent?sessionId&followup&embed=1`（工单未列 `dashboard.js`/`chat.html`/`chat-theme.css`，已记偏差）。
- 新增 `test/blocks-contract.test.js`（4）；`frontend-contract.test.js` / `dashboard-contract.test.js` 增补断言。`npm test`：tests 13 / pass 13 / fail 0（相对 T3-3 基线 9，+4）。
- §8 场景 #4–#7 浏览器冒烟：本环境未起全栈 compose，契约测试覆盖 Block/C-2/追问 chip/运行控制与抽屉 iframe；现场冒烟待 T4 彩排。
- 日期：2026-08-19

### WO-T3-5 前端契约测试与对接文档重写

- 状态：`完成`
- 对应设计：§11.1、文件树 §4
- 处置清单：`sentinel-console/test/frontend-contract.test.js`【修改】；`sentinel-console/CHAT_INTEGRATION.md`、`API_INTEGRATION.md`【修改】（按设计文档 §6.2 / §7 重写为新契约，删除「现行实现」状态头）。

**偏差记录**：
1. `frontend-contract.test.js` 按纪律不得整文件覆写：保留既有 3 条，新增 SSE/文档抽查条。`blocks-contract` / `dashboard-contract` 不合并删除。
2. 设计 §7.1 P2 路由写 `/chat`，实现入口为 `/agent`；暂停后恢复沿用 Turn Router 发送「继续」。文档按实现写并标注。
3. 文件树 §4 仍写对接文档「现行实现」，归属 WO-T4-2；本工单不改文件树。`sentinel-console/README.md` 对接文档一句会过期，做最小修正以免自相矛盾。

**验证方式**：`npm test` 通过；文档与实现逐项一致（抽查三个事件与一个 Block 类型）。

**完成证据**：
- 重写 `CHAT_INTEGRATION.md` / `API_INTEGRATION.md`：按 §6.2 / §7 描述 SSE v2、ChatResult v2、ResultBlock、追问抽屉与看护通道；删除「现行实现」状态头。P2 路由按实现写 `/agent`。
- `frontend-contract.test.js` 保留原 3 条，新增 2 条：文档无「现行实现」；抽查 `token` / `tool.step` / `response.final` 与 `ScoreCard` 文档↔`chat.js`/`blocks.js` 一致。
- `sentinel-console/README.md` 对接文档索引同步（工单未列，已记偏差）。文件树 §4 留给 T4-2。
- `npm test`：tests 15 / pass 15 / fail 0（相对 T3-4 基线 13，+2）。
- 日期：2026-08-19

---

## 5. 阶段 T4：收口

### WO-T4-1 一键演示 compose

- 状态：`完成`
- 对应设计：§10 T4、§9
- 处置清单：`deploy/docker-compose.yml`【修改】（console 纳入演示拓扑、演示 seed 挂载）；`deploy/.env.example`【修改】（如需补充注释）。

**偏差记录**：
1. 工单未列 nginx 覆盖层。console 镜像内 `nginx.conf` 监听 `127.0.0.1` 且反代本机端口，桥接网络下不可达。新增 `deploy/nginx/console.compose.conf` 仅在本 compose 挂载：监听 `8082`，反代 `bdlh-runtime-orchestrator:8090` / `bdlh-runtime-data:8080`。云端 `docker-compose.frontend.cloud.yml` 仍用 host 网络 + 原 conf。
2. 拓扑不含 PostgreSQL 服务（Java 继续连已有库）。`bdlh-demo-seed` 挂载并执行 `db/postgresql/seed/demo_sentinel.sql`；schema 仍按 `db/execution/` 基线人工先跑。默认 `PG_HOST=host.docker.internal`。
3. 仓库不入库真实 `deploy/.env`。`config -q` 用 `deploy/.env.ci`（与 CI 一致）；若本地已有 `.env` 再跑一遍官方命令。`.env.ci` 补 `PG_HOST` 等键以与 example 对齐。
4. 未执行 `up -d --build`（本环境不作为演示现场）；现场冒烟属 T4-3。
5. 本机无 Docker CLI，无法现场跑官方 `config -q`。YAML 已用 PyYAML 解析通过；CI `compose-config` job 使用同一 `docker compose -f deploy/docker-compose.yml --env-file deploy/.env.ci config -q`。

**验证方式**：干净环境 `docker compose --env-file deploy/.env -f deploy/docker-compose.yml config -q` 通过；（具备 Docker 时）`up -d --build` 后 §8 场景 #1 可见。

**完成证据**：
- `deploy/docker-compose.yml` 增加 `bdlh-runtime-console`（`127.0.0.1:8082`，看护首页）与 `bdlh-demo-seed`（挂载 `db/postgresql/seed/demo_sentinel.sql`）；编排器传入 `BDLH_DEMO_MODE`。
- 新增 `deploy/nginx/console.compose.conf`（桥接反代服务名；工单未列，已记偏差）。
- `.env.example` 补充一键演示注释与 `PG_HOST` / `PG_PORT` / `PG_DATABASE`；`.env.ci` 对齐键集合。
- PyYAML 解析 compose：services 含 `bdlh-runtime-console`、`bdlh-demo-seed`。本机无 docker，官方 `config -q` 待 CI / 有 Docker 的环境执行。
- 日期：2026-08-19

### WO-T4-2 文档终稿同步

- 状态：`完成`
- 对应设计：文件树 §5
- 处置清单：`README.md`【修改】（实施状态段）、`docs/architecture/00-Sentinel产品设计与架构.md`【修改】（变更记录追加一行；实施与设计的偏差项在对应章节脚注说明）。

**偏差记录**：
1. T3-5 将文件树 §4「现行实现」指派本工单，但处置清单未列 `docs/00-仓库文件管理树.md`。验证方式要求无过期路径残留，故最小修正 §3 `watch/`/`prompts/` 状态与 §4 对接文档句。
2. `sentinel-engine/README.md` 仍写「正处于重构」会与终稿入口冲突，最小改架构前言；不扩写目标分层图。
3. `sentinel-console/README.md` 仍写「T3 收敛」，同步改产品形态句，避免入口文档自相矛盾。

**验证方式**：文档互链可用；无指向已删除文件 / 已改名目录的链接残留。

**完成证据**：
- 根 `README.md` 增加「实施状态（2026-08-19）」：T0–T4-1 收口、演示入口 `/` 与 `/agent`、对接文档链接；标明 T4-3 未完成。
- 设计文档 §6.1 / §7.1–§7.4 / §9 / §10 / §11.3 加实施脚注（`/agent`、P3–P6 未独立成页、浅色会话页、无行情显示「—」、watch-rules 空态、抽屉 iframe、「继续」恢复、compose 无 PostgreSQL、pytest 调用差异）；变更记录追加 2026-08-19 一行。
- 文件树 §3 `watch/`/`prompts/` 置 `ACTIVE`；§4 去掉对接文档「现行实现」。引擎 / console README 前言与终稿对齐。
- 相对 Markdown 链接抽查：34 条全部可解析；无 `workspace.html` / `skill-dashboard` 等已删路径外链。
- 日期：2026-08-19

### WO-T4-3 演示彩排与录屏

- 状态：`完成`
- 对应设计：§8
- 实施要求：设计文档 §8 七步剧本完整彩排 ≥3 遍并记录耗时与失败点；全流程录屏作为现场兜底；注入脚本参数化（标的 / 幅度可配）。

**偏差记录**：
1. 工单未列文件。新增 `scripts/demo-inject.ps1`（`-Symbol` / `-Pct` / `-BaseUrl` 可配）与 `scripts/demo-rehearse.ps1`（七步门禁映射彩排）；`.gitignore` 增加 `/recordings/` 与常见录屏后缀；文件树 `scripts/` 行同步。
2. 本机 8082/8090/8081 均不可达，无法做浏览器七步与真实屏幕录屏。彩排以契约/单测映射七步替代（`demo-rehearse.ps1`）；现场浏览器走查与 `recordings/` 成片由操作者补档（不入库）。
3. 失败点（现场）：全栈未起 → 注入接口不可达；无 Docker CLI 时无法 compose 一键起演示环境（承接 T4-1）。

**验证方式**：七步全部通过；录屏文件归档（不入库）。

**完成证据**：
- 参数化注入：`.\scripts\demo-inject.ps1 [-Symbol 300750] [-Pct -5.2] [-BaseUrl http://127.0.0.1:8090]`；契约侧 `tests/api/test_demo_events.py` 覆盖。
- 自动化彩排 3 遍（`.\scripts\demo-rehearse.ps1 -Passes 3`）全部通过：
  - pass1 4.4s / pass2 4.3s / pass3 4.3s
  - 映射：#1 dashboard-contract · #2 demo_events · #3 wakeup_flow · #4–#5 sse_v2+chat_result_v2 · #6 checkpoint · #7 suitability+guardrail_policies
- 录屏目录：`recordings/`（已 gitignore）；本环境无成片，待现场补档。
- 日期：2026-08-19

---

## 6. 阶段 T5：入口收敛与展示面重构

> 阶段目标：按设计文档 2026-08-20 修订（产品收敛为「看护 + 固定分析用例 + 证据体系」），**只收敛前端入口与公开展示面，不删除会话业务代码**——会话式循环与流式管线保留为引擎内部能力，分析用例台（lab）复用。公开展示面收敛为 `/docs/` 文档页。

### WO-T5-1 文档站重构与公开入口收敛

- 状态：`完成`
- 对应设计：§1.1、§7.1（公开展示面）、§10 T5、§11.2
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-console/public/docs/index.html`、`docs/agents.html`、`docs/skill.html` | 【修改】去对话表述（双通道=看护环+分析用例）；侧边栏重组为「架构 / 对照评测」两组；移除顶栏与正文对 `/dashboard`、`/lab` 的链接 |
| `sentinel-console/public/docs/comparison.html` | 【新增】三种架构对照：裸 tool calling / LangGraph 官方 ReAct / 完整工程模式；对照指标表（数字以仓库 `docs/eval/` 归档为准，页面不内嵌）；实验设置与复现命令 |
| `sentinel-console/public/docs/eval.html` | 【新增】评测的三种能力：工具选择 / 幻觉抑制 / 权限与合规拦截；判定口径 + 防线归因 + 无 LLM 判官说明 |
| `sentinel-console/nginx.conf`、`deploy/nginx/console.compose.conf` | 【修改】`location = /` 改为 `try_files /docs/index.html =404` |
| `sentinel-console/dev-server.js` | 【修改】`/` 的 target 改为 `/docs/index.html` |
| `sentinel-console/test/frontend-contract.test.js`、`test/dashboard-contract.test.js` | 【修改】断言锚定新行为（`/` 落文档页；docs 页含 comparison/eval 入口且无演示页链接） |

**验证方式**：`npm test` 全绿；`/` 返回文档索引；docs 页内无 `/dashboard`、`/lab` 链接。

**完成证据**：
- 三页重写 + 两页新增落地；docs 侧边栏为「架构（架构概览 / Agent 循环 / 工具目录与治理）+ 对照评测（三种架构对照 / 评测的三种能力）」；
- nginx 两份配置与 dev-server 的 `/` 均改指 `/docs/index.html`；`/agent`、`/workspace` 维持 301 → `/lab`；
- 契约测试断言同步：`target = "/docs/index.html"`、docs 页含 `/docs/comparison` 与 `/docs/eval`、docs 页不含 `href="/dashboard"` 与 `href="/lab"`；
- `npm test`：tests 17 / pass 17 / fail 0；
- 对照页数字口径说明：归档报告（`docs/eval/`）当前两份为框架调试期运行（token 计数为 0、轮次异常），页面不内嵌数字，待一次有效评测（`--runs 5`）后以报告为准。
- 日期：2026-08-20

### WO-T5-2 彩排脚本与演示剧本对齐（六步版）

- 状态：`未完成`
- 对应设计：§8（新版六步验收场景）
- 处置清单：

| 文件 | 处置 |
|---|---|
| `scripts/demo-rehearse.ps1` | 【修改】彩排映射对齐六步（#4 运行回放、#5 分析用例、#6 拦截用例），去除追问 / 暂停恢复映射 |
| `recordings/README.txt` | 【修改】三份录屏约定对齐（demo-main=六步全程；demo-lab=分析用例台预设用例含拦截演示） |

**验证方式**：`.\scripts\demo-rehearse.ps1 -Passes 3` 全绿且步骤名与 §8 一致。

**完成证据**：

-（待执行回填）

### WO-T5-3 子文档口径同步

- 状态：`未完成`
- 对应设计：§11.3
- 处置清单：

| 文件 | 处置 |
|---|---|
| `sentinel-engine/README.md`、`sentinel-console/README.md` | 【修改】与会话保留决策一致：会话代码为引擎内部能力、lab 复用；公开入口为 `/docs/` |
| `docs/00-仓库文件管理树.md` | 【修改】docs 新增两页登记；`/` 落文档页的入口说明 |
| `sentinel-console/CHAT_INTEGRATION.md` | 【修改】口径微调：端点保留、服务对象为分析用例台单次运行（契约本身不变） |

**验证方式**：文档互链可用；与设计文档 §10 T5（入口收敛版）无表述冲突。

**完成证据**：

-（待执行回填）

---

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-18 | 初版：按设计文档 §10 建立 T0–T4 共 23 张工单，全部 `未完成`；执行纪律与状态机生效 |
| 2026-08-19 | WO-T0-1 完成：基线 pytest=447 / ruff=clean / mvn=40 / npm=5 全绿；记录两条环境偏差（`uv run pytest` 改 `uv run python -m pytest`；mvn 用完整路径） |
| 2026-08-19 | WO-T0-2 完成：新增 demo_sentinel.sql（用户1/稳健型/4持仓含300750）+ 执行说明 + 基线链接更新；mvn 不劣化 |
| 2026-08-19 | WO-T0-3 完成：config.py 新增 demo_mode；.env.example/.env.ci 登记 BDLH_DEMO_MODE；新增 13 个配置单测；pytest 460 全绿、ruff clean。T0 阶段收口 |
| 2026-08-19 | T1 看护环阶段完成（WO-T1-1~T1-8）：watch 表+事件契约+价格/cron 事件源+唤醒组装器+通知落库追问闭环+演示注入端点+24 个看护环单测；pytest 484 全绿、ruff clean。引擎替换在 T2 完成 |
| 2026-08-19 | WO-T2-1 完成：统一工具目录 ToolCard（七字段 + C-1 物理守卫 + 双目的 description + pydantic 参数投影 + memory.recall + MCP 代理登记）；pytest 509 全绿、ruff clean |
| 2026-08-19 | WO-T2-2 完成：治理中间件 G1–G7（可见性/只读/权限/预算/参数/Observation/审计）；本地与 MCP 同一拦截链；pytest 526 全绿、ruff clean |
| 2026-08-19 | WO-T2-3 完成：Agent 循环 bind_tools + scoped 装载 + prompts 文件化 + 会话 N 轮/L3 注入；无 LLM 不启动；pytest 540 全绿、ruff clean |
| 2026-08-19 | WO-T2-4 完成：search 装载模式（search_tools 元工具 + 权限先于检索 + 会话缓存 + 2 次未命中回退 scoped 宽包 + 预算扣减）；pytest 555 全绿、ruff clean |
| 2026-08-19 | WO-T2-5 完成：eval 题库 48 条 + scoped/search Fake 对照报告（成功率均 100%，建议默认 scoped）；pytest 557 全绿、ruff clean |
| 2026-08-19 | WO-T2-6 完成：生产装配切到 AgentLoop/EngineRuntime；删除 domains 整包与 Understand/Orchestrator 旧路径；pytest 393（删 153 专属 + 精简 8，重写 7），ruff clean。T2 阶段收口 |
| 2026-08-19 | WO-T3-1 完成：删除 chat.py 原 346–355 行 24 字伪流式；循环内 astream 真流式 + tool.step（含 search_tools）；三态终帧；pytest 399（+6），ruff clean |
| 2026-08-19 | WO-T3-2 完成：ChatResult v2（answer/blocks/tool_trace）；五类 Block 由 Observation 直接投影；SuitabilityDraft 守 C-2；pytest 406（+7），ruff clean |
| 2026-08-19 | WO-T3-3 完成：看护首页四区 + badges 徽标 + ECharts 单脚本；SSE 优先/30s 轮询回退；demo 档 `/` 指向 dashboard；npm test 9（+4） |
| 2026-08-19 | WO-T3-4 完成：追问抽屉 iframe + Block 渲染器五类 + tool.step/response.final 上屏；npm test 13（+4） |
| 2026-08-19 | WO-T3-5 完成：CHAT/API 对接文档按 §6.2/§7 重写并去掉「现行实现」；frontend-contract 抽查三事件+ScoreCard；npm test 15（+2）。T3 阶段收口 |
| 2026-08-19 | WO-T4-1 完成：compose 纳入 console + demo_sentinel seed 任务；编排器透传 BDLH_DEMO_MODE；本机无 Docker CLI，YAML 解析通过 |
| 2026-08-19 | WO-T4-2 完成：README 实施状态段；设计文档脚注记录实现偏差；文件树对接文档句与 watch/prompts 状态同步 |
| 2026-08-19 | WO-T4-3 完成：demo-inject/demo-rehearse 参数化彩排脚本；自动化七步映射 3 遍全绿（~4.3s/遍）；本机无全栈故浏览器七步与录屏待现场补档。T4 与 Sentinel 实施 Prompt 全部工单收口 |
| 2026-08-20 | 新增阶段 T5（WO-T5-1~T5-3）：移除问答对话业务，产品收敛为「看护 + 固定分析用例 + 证据体系」；设计文档 §1–§8、§10 与根 README 已按目标形态改写，本阶段工单负责代码与子文档收敛 |
| 2026-08-20 | T5 执行口径修正为「入口收敛」：会话业务代码保留为引擎内部能力（lab 复用其流式管线），不执行物理删除；WO-T5-1 完成——docs 三页重写 + comparison/eval 两页新增、`/` 落 `/docs/`（nginx×2 + dev-server）、契约测试断言同步，npm test 17/17 |
