# Live 真实执行服务设计：整体 Agent 逻辑一次调用全部走通

> 状态：设计稿（待评审）
> 分支：`touchstone`
> 日期：2026-08-31
> 范围：engine / data / db / web 四层各一处增量，不改动既有评测路径

---

## 1. 背景与问题诊断

本仓库目前是一个**受控评测装置**，不是一个真实运行的服务。逐层核对代码后，真实与未落地的边界如下：

### 1.1 已经是真实的部分（可直接复用）

| 环节 | 位置 | 现状 |
|---|---|---|
| LLM 调用 | `engine/src/bdlh_runtime/infra/llm.py` | langchain-openai → OpenAI 兼容端点（`deploy/.env` 已配 SiliconFlow），原生 tool calling、流式、温度逐运行生效 |
| Agent 循环 | `engine/src/bdlh_runtime/engine/loop.py` | G-α 快路径 → 上下文构建 → G-β 原生循环 → 治理中间件 → Observation 回填，全部真实现 |
| 治理中间件 | `guardrails/middleware.py` | G1–G7 拦截链、写确认、审计记录完整 |
| 上下文构建 | `context/builder.py` | 分类/预算/跨用户隔离/不可信包裹，真实现 |
| 语义路由 | `engine/semantic_router/` | Qwen 向量编码器 + 三路由阈值实测校准 |
| 运行遥测 | `evaluation/run_telemetry.py` + `run_event_bus.py` | events/model_calls/tool_calls/guardrail_checks 四类明细 + SSE 实时发布 + 增量落库，真实现 |
| 持久化 | Java data 服务 + PostgreSQL | 37 张表，批次/运行/明细/审计全量落库 |
| 部署 | `.local-services/`、`deploy/` | 本地四进程栈（PG 5432 / data 18081 / engine 8090 / web 8082）当前可跑 |

### 1.2 未落地的部分（本设计要解决的缺口）

1. **模型看到的每一个工具结果都来自冻结 fixture，从未发生过一次真实工具执行。**
   - 模板/实验组运行：`experiments/template_runner.py:286` 固定 `FrozenFixtureExecutor`；
   - 压缩用例：`session/mock_dispatcher.py` 按 gold 返回冻结结果；
   - 对照评测：`evaluation/frozen_observations.py` 读 `fixture_tool_responses` 表。
2. **真实工具执行层存在但从未装配。** `engine/executor.py` 的 `CatalogToolExecutor` 预留了五个适配器插槽（gateway/MCP、java、web_search、analysis、deep_research），`src/` 中没有任何调用方；`integrations/mcp/`、`tools/deep_research/` 是空目录。
3. **数据服务没有业务数据端点。** `data/` 只有题库、批次、运行、上下文工作台等评测设施，`portfolio.*`/`user.*`/`market.*` 标注的 java/mcp 适配器在数据面无对应实现。
4. **没有面向用户的对话入口。** `run_api.py` 全部端点都是实验管理接口；`EngineRuntime`/`InputEvent` 契约层（chat/唤醒适配）没有任何路由调用它。
5. **工具目录真源未被服务使用。** DB 八表注册了 112 个工具，`registry/loader.py` 支持从 data 服务加载校验，但正式运行一律用代码内冻结快照 `comparison-catalog-v1`。

**结论：需要补的不是"再写一个 agent 框架"，而是把已存在的真实组件按生产形态装配起来，并补上唯一缺失的一层——真实工具数据平面和一个对话入口。**

---

## 2. 目标与非目标

### 目标

一次用户调用完整走通下列链路，且每一跳可观测、可复查：

```
登录会话 → POST /api/v1/live/chat
  → G-α 语义快路径(闲聊/知识/禁止)
  → 上下文构建(预算/隔离/系统提示)
  → G-β 原生 tool calling 循环(bind_tools → 模型决策)
  → 治理中间件 G1–G7(可见性/只读/权限/预算/参数校验)
  → 真实工具执行(engine 适配器 → data 服务 HTTP → PostgreSQL)
  → Observation 回填 → 循环直至最终回答
  → 出口护栏(合规 + 数字接地)
  → 遥测落库(events/model_calls/tool_calls/guardrail_checks)
  → SSE 实时输出 → 运行详情页复查
```

### 非目标

- 不替换、不改动既有评测路径（模板/实验组/压缩对照继续用冻结 fixture，保证实验可比性）；
- 第一期不接外部真实行情源（见 §8 决策 D2，预留替换位）；
- 不做任何写操作工具（只读红线不放松）；
- 不做主动看护/唤醒/消息队列（README 已明确不属于本系统）。

---

## 3. 总体架构

```
用户浏览器
   │  http://127.0.0.1:8082/live/
   ▼
web 静态站(dev-server/nginx 反代白名单 +1 段)
   │  POST /api/v1/live/chat/stream   (Bearer 会话)
   ▼
engine run_api  ── 新增 /api/v1/live/* 路由(登录态)
   │
   ▼
LiveAgentService(新包 bdlh_runtime/live/)
   ├─ 装配(一次性): DB 工具目录真源 + finance 场景包 + create_llm + 语义快路径
   ├─ AgentLoop(scoped 装载, research 场景) + RunRecorder/RecordingLLM/RecordingExecutor
   │      │                    │
   │      │ 治理中间件 G1–G7    │ 遥测事件流
   │      ▼                    ▼
   │  CatalogToolExecutor    RunEventPublisher ──→ SSE 订阅者
   │   ├─ LiveMarketAdapter(market.*)   ─┐
   │   ├─ LivePortfolioAdapter(          ├─→ HTTP X-Internal-Token
   │   │    portfolio.*/user.*)          │
   │   └─ 确定性估值(已有实现)           ▼
   │                              data 服务 /internal/v1/live/*（新）
   │                                ├─ LiveMarketRepository
   │                                └─ LivePortfolioRepository
   │                                      ▼
   │                              PostgreSQL live_* 表（新，种子数据）
   ▼
每 turn 一条 agent_runs 行 + 四类明细
   → 既有批次列表/运行详情/工具调用检索/SSE 断线补发 全部零改动复用
```

关键原则：**live 链路只新增"数据平面 + 装配 + 入口"，循环、治理、遥测、可观测全部复用既有真实现；live 运行与实验运行同构落库。**

---

## 4. 数据平面设计（db + data 服务）

### 4.1 新表（迁移脚本 `db/postgresql/changes/20260831-live-tool-data.sql`）

全部为只读业务事实表，前缀 `live_` 与评测表隔离：

| 表 | 主键 | 说明 |
|---|---|---|
| `live_instruments` | symbol | 标的主数据（名称/市场/币种/行业） |
| `live_quotes` | symbol | 最新报价快照（价/涨跌幅/量额/更新时间） |
| `live_price_history` | (symbol, trade_date) | 日 OHLCV |
| `live_fundamentals` | (symbol, report_period) | 财报与估值指标（营收/净利/ROE/PE/PB…） |
| `live_industry_context` | symbol | 行业归属与背景 |
| `live_money_flow` | symbol | 资金流向摘要 |
| `live_news` | id | 结构化新闻 |
| `live_accounts` | account_id | 账户现金快照 |
| `live_positions` | (account_id, symbol) | 持仓 |
| `live_transactions` | id | 已发生成交流水 |
| `live_risk_profiles` | account_id | 风险画像 |

同时登记 `live-chat` 用例（`case_definitions`/`case_versions`/`case_variants`/`data_snapshots` 各一行，`public=false`），因为 `agent_runs` 对 `(case_id, version, variant_id)` 与 `snapshot_id` 有外键——live 运行需要合法引用。此用例不进公开题库。

### 4.2 种子数据策略

- 标的集合：A 股（600519 贵州茅台、300750 宁德时代、601318 中国平安）+ 港股（00700）+ 美股（AAPL、NVDA），覆盖多币种多市场；
- 历史价格：SQL `generate_series` + 确定性三角函数序列生成约 250 个交易日（可复现、无随机数）；`live_quotes` 取序列末值，保证报价与历史末端一致；
- 持仓/账户/画像：`INSERT … SELECT` 为**已存在的每个账号**生成同一套演示组合（`ON CONFLICT DO NOTHING` 幂等），任何现有账号登录即可用；
- 脚本遵循 changes/README 规范：BEGIN/COMMIT、锁超时、幂等可重跑、登记 `database_changes`。

### 4.3 data 服务端点（新 `LiveToolDataController`，挂既有 `/internal/v1` + 内部令牌拦截器）

```
GET /internal/v1/live/market/resolve?query=          名称/代码 → 标准标的
GET /internal/v1/live/market/quote?symbol=           最新报价
GET /internal/v1/live/market/history?symbol=&days=   OHLCV 序列
GET /internal/v1/live/market/statements?symbol=      财务报表
GET /internal/v1/live/market/valuation?symbol=       估值指标
GET /internal/v1/live/market/industry?symbol=        行业背景
GET /internal/v1/live/market/money-flow?symbol=      资金流
GET /internal/v1/live/market/news?symbol=            结构化新闻
GET /internal/v1/live/portfolio/positions?accountId= 持仓
GET /internal/v1/live/portfolio/account?accountId=   账户快照
GET /internal/v1/live/portfolio/transactions?accountId= 成交流水
GET /internal/v1/live/users/risk-profile?accountId=  风险画像
```

实现形态对齐既有 `ToolFixtureRepository` 风格：`JdbcTemplate` + 两个新 Repository（`LiveMarketRepository`/`LivePortfolioRepository`），纯只读查询，无新依赖。

---

## 5. 引擎设计（engine 新包 `bdlh_runtime/live/`）

### 5.1 真实工具适配器（`live/adapters.py`）

- `LiveMarketAdapter`：`market.*` → §4.3 market 端点（对应 `CatalogToolExecutor` 的 gateway 插槽）；
- `LivePortfolioAdapter`：`portfolio.get_current_positions` / `get_account_snapshot` / `get_transaction_history`、`user.get_risk_profile` → §4.3 portfolio/user 端点（对应 java 插槽）；持有当前登录 `accountId`（`set_user`，按运行注入，杜绝跨用户读取）；
- `portfolio.build_current_valuation`：走 `CatalogToolExecutor` 已有的确定性估值实现，不新增代码；
- 适配器经 `DataClient` 新增方法调用（端点/令牌/超时单一真源）；
- 返回值为领域数据 dict，由治理中间件统一包装为 `Observation`（与评测链路同构）；数据服务不可达 → 异常 → 中间件结构化 FAILED，不静默。

### 5.2 LiveAgentService（`live/service.py`）

**装配（进程内一次，锁保护，fail-fast 与可降级并存）：**

1. 工具目录：`DataClient.get_tool_catalog()` → `registry/loader.load_and_validate_payload()` → `catalog_from_snapshot()`——**第一次让 DB 八表目录真源进入服务运行**（替代冻结快照）；
2. 场景包：`enable_scenario_pack("finance")`（幂等），获得 research/market/portfolio 场景映射、危险动作词表、出口护栏关键词、双目的工具描述；
3. LLM：`create_llm(env)`，未配置则诚实降级（`LLM_UNAVAILABLE`，不兜底）；
4. 语义快路径：`QwenEmbeddingEncoder`（复用 LLM_BASE_URL/API_KEY + `FASTPATH_EMBEDDING_MODEL`）+ `fastpath_data.MODEL_FASTPATH_THRESHOLDS` 构建 `SemanticRouter`；embedding 服务不可用则跳过（记日志，G-α 缺席但主链路完整）。

**执行一次 turn（`chat(account, session_id, message, sink)`）：**

1. 取/建会话（内存存储：多轮 `history` + turn 索引，容量上限）；
2. 提前建行：`create_run`（batch=本会话 live 批次、case=`live-chat`）取得 runId → `register_publisher(RunEventPublisher(runId, flush=save_events))`——复用既有 SSE 断线补发与增量落库；
3. 组装：`RunRecorder` + `RecordingLLM` + `RecordingExecutor(CatalogToolExecutor(真实适配器))` + `AgentLoop(tool_loading="scoped", scene="research", max_agent_steps=…)`；
4. 执行：`AgentLoop.run(AgentTurn(authenticated=True, history=会话历史))`，流式 sink 桥接为 SSE `token`/`tool` 事件；
5. 收尾：出口护栏（`OutputGuardrail` C1/C2 合规 + 数字接地，finance 包关键词已就绪）→ `record_output` → 明细落库（复用 `_persist_run_details` 模式：events→model_calls→tool_calls→guardrail_checks→measurements）→ `complete_run`（INVALID/FAILED 诚实透传）；
6. 会话历史追加本轮 user/assistant 消息。

### 5.3 run_api 路由（登录态）

| 路由 | 说明 |
|---|---|
| `POST /api/v1/live/chat` | JSON 一次性返回（answer + 工具轨迹 + runId + 停止原因） |
| `POST /api/v1/live/chat/stream` | SSE：`meta` → `token`* → `tool`* → `done`；执行放工作线程，队列桥接，天然支持慢消费者 |
| `GET /api/v1/live/tools` | 当前装配的真实工具目录（透明化） |
| `GET /api/v1/live/sessions` / `GET /api/v1/live/sessions/{id}` | 会话列表与历史（含每 turn runId，可跳转运行详情） |

既有 `GET /api/v1/runs/{id}/events/stream` 与运行详情接口对 live 运行**零改动可用**（发布器按 runId 注册）。

---

## 6. 前端（web）

- 新增 `web/public/live/`：对话控制台——登录、会话切换、SSE 流式回答、工具调用步骤实时展示（工具名/参数/状态/耗时/审计码）、完成后附 runId 深链到既有运行详情页；风格对齐现有静态站；
- `web/scripts/owner-api-allowlist.mjs` 增加 `live` 段（dev-server 与 nginx 反代共用该清单，一处修改两处生效）；
- `web/public/index.html` 等导航入口补链接。

---

## 7. 关键设计决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 工具结果真源 = data 服务 HTTP → PostgreSQL，而非引擎内造数 | "真实落地"的核心是**链路真实**；沿用仓库既有边界（engine 不直连 DB） |
| D2 | 行情为静态种子快照，接口带 `asOf`，不冒充实时 | 遵守仓库"不得冒充真实数据"原则；接真实行情源时只替换种子/刷新链路，链路与其余层不动 |
| D3 | `research.web_search`/`research.deep_search`/`analysis.run_analysis` 从 live 目录**排除** | 无真实后端就诚实不可用，绝不写假实现；评测路径不受影响 |
| D4 | live 运行与实验运行**同构落库**（同表同明细同 SSE） | 可观测面零新增；live 流量天然成为工程验证数据源 |
| D5 | 安全边界全部照常：只读红线、G3 权限（portfolio 工具需登录）、预算上限、`live-chat` 用例不公开 | 真实服务不因演示降低治理强度 |
| D6 | 会话先内存态（上限+淘汰），运行明细已全量在 DB | 首期最小可用；历史可由 DB 运行记录重建，后续可平移到 data 服务会话表 |
| D7 | 复用 `RunRecorder/RecordingLLM/RecordingExecutor` 而非新写遥测 | live 与实验遥测口径一致，统计/对比页可直接消费 |

## 8. 实施步骤与验收

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| P1 | DB 迁移脚本 + 种子数据 | 脚本幂等重跑通过；抽查明细 SQL 正确；`database_changes` 登记 |
| P2 | data 服务 live 端点 | `mvn test` 通过；curl 抽查 12 个端点返回结构正确；错误路径 404/空集诚实 |
| P3 | engine live 包 + run_api 路由 | ruff/pytest 通过；LLM 不可用时诚实降级；单测覆盖适配器映射与装配 |
| P4 | web 控制台 + 代理白名单 | `npm test` 通过；页面经 8082 反代完成一次完整对话 |
| P5 | E2E 验证 + 回归 | 见 §9 |

## 9. 端到端验证方案（P5）

1. `start-all` 起栈 → 执行迁移 → 重启 data/engine；
2. `POST /api/v1/login`（owner）→ `POST /api/v1/live/chat/stream`，问题："贵州茅台现在什么价？顺便看看我现在的持仓市值多少。"；
3. 断言：
   - SSE 依次出现 `tool`（`market.resolve_instrument` → `market.get_realtime_quote` → `portfolio.get_current_positions` → `market.get_realtime_quote`(批量) 或确定性估值）与 `token` 流；
   - 回答中的价格/市值数字与 `live_quotes`/`live_positions` 种子值一致（数字接地）；
   - data 服务访问日志/`tool_calls` 表出现对应行，`simulated=false`（真实执行）；
   - 运行详情页可打开该 runId，四类明细齐全；
   - 闲聊句（"你好"）命中 chitchat 快路径不进循环；越权/未登录调 portfolio 工具被 G3 拒绝并留审计码；
4. 回归：`engine: ruff + pytest`；`data: mvn test`；`web: npm test`；compose `config -q`。

## 10. 风险与开放问题

- **embedding 可用性**：SiliconFlow embeddings 与聊天模型同源，故障时 G-α 缺席——已设计为可降级，主链路不受影响；
- **会话持久化**：首期内存态，重启丢多轮上下文（明细仍在 DB）——是否平移到 data 服务会话表，视使用频率决定；
- **真实行情源**：接入外部行情（或 MCP 网关）是第二期自然延伸，本设计的适配器插槽即为其预留位；
- **并发与限流**：live 入口沿用 `MAX_CONCURRENT_BATCHES` 信号量思路，按账号加并发上限，防止对话流量挤占实验预算；
- **成本**：每 turn 是真实 LLM 调用，控制台默认展示 token 用量（遥测已有），便于观察。
