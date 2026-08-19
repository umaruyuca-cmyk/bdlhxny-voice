# BDLH 入口理解与资格菜单重写 — 可交付实施 Prompt

> **文档状态：本重写任务的唯一执行 Prompt**  
> **版本：v1.0**  
> **日期：2026-08-15**  
> **适用仓库：** `bdlh-runtime-orchestrator`（工作区 `D:\bdlh-agent\bdlhxny-agent`）  
> **需求真源：** 桌面 `BDLH-语义路由与工具菜单-需求更新.md`（2026-08-15 修订冻结稿）  
> **入口真源：** `f:\qq\BDLH-语义路由与意图理解-讨论整理.md`（2026-08-13）  
> **现网总 Prompt：** `docs/prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md`  
>   本文件**覆盖** 00 号中与 QueryIntent / `analysis_type` / 按类型规划工具 相关的段落；  
>   不覆盖 M0 发布门禁、M3 快照规则、ADR-016 Deep Research。  
> **策略：** 现网不打补丁。一次重写切换。`analysis_type` **一步删除**。资格与工具目录 **只在数据库**。

---

## 0. 怎么用这份 Prompt

把本文完整交给执行 Agent / 工程师，并附加：

```text
TASK: REWRITE_ENTRY_AND_TOOL_MENU
BRANCH: 由执行者新建（本 Prompt 不指定分支名；未授权则只出 diff 不出 push）
DB: 使用环境变量 POSTGRES_DSN；测试可用独立 schema 或 Testcontainers
OUT_OF_SCOPE: ADR-016 Deep Research；匿名 actor_id 改造；程序记忆晋升；新建 Skill
```

完成标准：§12 验收全绿 + `rg analysis_type` 在 `bdlh-runtime-orchestrator/src` 与 `tests` 中为零（允许注释/变更日志中的删除说明）。

角色：你是本仓库的 Runtime 工程师。必须读现网代码再改，禁止另起示例工程。禁止内置第二份工具清单兜底。

---

## 1. 硬规则（违反即不合格）

1. LLM 不发放通行证；用户原句不参与 `effective_operations` / `eligible`。  
2. 理解节点 `tools = []`，禁止输出 `route` / `skill_id` / `analysis_type` / `plan_steps`。  
3. `requested_topics[]` **只允许** `news | money_flow | industry | web_research`，禁止 `valuation` / `technical` / `comprehensive` 等体裁；**不得缩小 `allowed`**。  
4. `allowed` 是稳定源。向量/分组只决定提示词窗口，不准从 `allowed` 删除工具。  
5. 向量失败对窗口 **fail-open**（退回分组或完整 `allowed`）。快路径未过线是 `None`，进理解，不是失败。  
6. Agent 每步只许 `CALL_TOOL` / `OPEN_TOOLSET` / `EXPAND_WINDOW` / `FINISH`。`FINISH` 只是建议，由 `GoalCoverage` 控制器决定。  
7. 配置真源是 Postgres。代码禁止 `build_default_capability_registry()` 式硬编码目录；库空或校验失败 **拒绝启动**。  
8. 只读：`read_only=false` 的能力不得进 Agent 菜单。  
9. 本次 **不做** 匿名入口（保持 `authenticated_user_id` 现网约束）。§2 需求稿里的 `actor_id` 不在本 Prompt 范围。  
10. 本次 **不做** Deep Research / `research.deep_search`。现有 `research.web_search` 仅作为一条普通 Capability 登记。

---

## 2. 重写后主路径（必须实现成这条，不得保留旧三模式路由）

```text
User
  → 门控（ADR-014 续跑/换题；只读；Skill 是否启用——读库）
  → 快路径 Semantic Router（样句读库：chitchat / knowledge / forbidden）
        过线 → RESPOND 或 BLOCK，结束
        未过线 → 理解 LLM
  → 理解 LLM → goals[] / entities / constraints / missing / needs_external
        missing 非空 → ASK_USER
        needs_external=false → RESPOND（无工具）
        needs_external=true → 读库算 eligible → allowed → 窗口 → Agent 循环
  → Agent：窗口内选一步 → Gateway（再核 ∈ allowed）→ Observation
        GoalCoverage 全 COVERED → 回答
        否则扩窗口或再选；预算耗尽 → PARTIAL/LIMITED
```

删除：`direct_response / single_capability / agent_loop` 作为理解后的业务分流  
（快路径 RESPOND 可以留，但不得再叫 `IntentRoute.mode=direct_response` 去裁工具）。

---

## 3. 数据库

沿用现网表前缀 `bdlh_runtime_`，与 `bdlh_runtime_chat_session` 同一 `POSTGRES_DSN`。

### 3.1 新文件

| 路径 | 作用 |
|---|---|
| `bdlh-runtime-orchestrator/src/bdlh_runtime/registry/schema.sql` | DDL，启动时执行（`IF NOT EXISTS`） |
| `bdlh-runtime-orchestrator/src/bdlh_runtime/registry/seed.sql` | 首次空库种子；已有行则跳过（按主键） |
| `bdlh-runtime-orchestrator/src/bdlh_runtime/registry/loader.py` | 启动加载 + fail-fast 校验 |
| `bdlh-runtime-orchestrator/src/bdlh_runtime/registry/store.py` | Postgres 访问 |
| `bdlh-runtime-orchestrator/src/bdlh_runtime/registry/models.py` | 只读 dataclass/Pydantic，无目录常量 |
| `bdlh-runtime-orchestrator/src/bdlh_runtime/registry/menu.py` | `effective_operations` / `eligible` / `allowed` / 窗口算法 |
| `bdlh-runtime-orchestrator/tests/registry/test_schema_and_seed.py` | 空库启动、种子、校验失败拒启 |
| `bdlh-runtime-orchestrator/tests/registry/test_menu.py` | 交集与窗口，不依赖 LLM |

测试可用 SQLite 仅当 SQL 方言兼容；**推荐**对 DDL 用 Postgres。若必须无 PG 单测，用 loader 的内存仓储接口，但生产路径只读 PG。

### 3.2 DDL（必须原样实现，列名可加但不得删）

```sql
-- bdlh_runtime/registry/schema.sql

CREATE TABLE IF NOT EXISTS bdlh_runtime_operation (
    code            VARCHAR(64) PRIMARY KEY,  -- READ_MARKET_DATA 等
    description     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_toolset (
    name            VARCHAR(64) PRIMARY KEY,  -- market_read
    description     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_capability (
    name            VARCHAR(128) PRIMARY KEY, -- market.get_realtime_quote
    description     TEXT NOT NULL,
    domain          VARCHAR(32) NOT NULL,
    adapter         VARCHAR(16) NOT NULL,     -- mcp | java | web | local
    read_only       BOOLEAN NOT NULL DEFAULT TRUE,
    requires_authenticated_user BOOLEAN NOT NULL DEFAULT FALSE,
    required_arguments TEXT[] NOT NULL DEFAULT '{}',
    depends_on      TEXT[] NOT NULL DEFAULT '{}',  -- 前置 capability 名
    output_schema   VARCHAR(64) NOT NULL DEFAULT 'Observation',
    timeout_seconds INTEGER NOT NULL DEFAULT 20,
    cost            INTEGER NOT NULL DEFAULT 1,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_capability_operation (
    capability_name VARCHAR(128) NOT NULL REFERENCES bdlh_runtime_capability(name),
    operation_code  VARCHAR(64)  NOT NULL REFERENCES bdlh_runtime_operation(code),
    PRIMARY KEY (capability_name, operation_code)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_capability_toolset (
    capability_name VARCHAR(128) NOT NULL REFERENCES bdlh_runtime_capability(name),
    toolset_name    VARCHAR(64)  NOT NULL REFERENCES bdlh_runtime_toolset(name),
    PRIMARY KEY (capability_name, toolset_name)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_skill (
    skill_id        VARCHAR(64) PRIMARY KEY,
    skill_version   VARCHAR(64) NOT NULL,
    domain          VARCHAR(32) NOT NULL,
    status          VARCHAR(32) NOT NULL,  -- CURRENT | FOUNDATION | EXPERIMENTAL
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    side_effects_empty BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_skill_operation (
    skill_id        VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_skill(skill_id),
    operation_code  VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_operation(code),
    required        BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_id, operation_code)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_skill_capability (
    skill_id          VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_skill(skill_id),
    capability_name   VARCHAR(128) NOT NULL REFERENCES bdlh_runtime_capability(name),
    required          BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_id, capability_name)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_runtime_allowlist (
    runtime_id      VARCHAR(64) NOT NULL DEFAULT 'default',
    operation_code  VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_operation(code),
    PRIMARY KEY (runtime_id, operation_code)
);

-- account_id = '*' 表示产品默认 entitlement
CREATE TABLE IF NOT EXISTS bdlh_runtime_account_entitlement (
    account_id      VARCHAR(64) NOT NULL,
    operation_code  VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_operation(code),
    PRIMARY KEY (account_id, operation_code)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_fastpath_route (
    name            VARCHAR(32) PRIMARY KEY,  -- chitchat | knowledge | forbidden
    score_threshold DOUBLE PRECISION NOT NULL,
    disposition     VARCHAR(16) NOT NULL,     -- RESPOND | BLOCK
    response        TEXT
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_fastpath_utterance (
    id              BIGSERIAL PRIMARY KEY,
    route_name      VARCHAR(32) NOT NULL REFERENCES bdlh_runtime_fastpath_route(name),
    utterance       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_run_budget (
    profile         VARCHAR(64) PRIMARY KEY,  -- default | research
    react_round_limit INTEGER NOT NULL,
    tool_call_limit   INTEGER NOT NULL,
    subgraph_timeout_seconds INTEGER NOT NULL,
    request_timeout_seconds INTEGER NOT NULL
);
```

启动校验（`loader.py`，失败抛 `ConfigurationError`，进程退出）：

- 每条 capability 至少 1 个 operation、1 个 toolset  
- `depends_on` 全部存在  
- `read_only=false` 不得 `enabled=true`（v1）  
- skill 引用的 capability/operation 必须存在  
- `enabled=true` 的 skill 其 required operations ⊆ runtime allowlist  
- 默认 entitlement `account_id='*'` 必须存在  
- 快路径仅允许三名：`chitchat` / `knowledge` / `forbidden`，且 utterance 非空  
- **零 capability 行 → 拒绝启动**（禁止代码兜底）

### 3.3 种子数据（`seed.sql`，与现网目录对齐后去掉 `analysis_types`）

**operations：**  
`READ_MARKET_DATA` `READ_PUBLIC_RESEARCH` `READ_PORTFOLIO` `READ_PROFILE` `READ_FINANCIAL_GOALS` `RUN_ANALYSIS` `PROPOSE_TASK`

**toolsets：**  
`market_read` / `fundamental_read` / `news_read` / `portfolio_read` / `financial_profile_read` / `planning_compute` / `plugin_probe_compute`  
描述沿用 `tools/toolsets.py` 中 `_TOOLSET_DESCRIPTIONS`。

**runtime allowlist (`default`)：**  
`READ_MARKET_DATA` `READ_PUBLIC_RESEARCH` `READ_PORTFOLIO` `READ_PROFILE` `READ_FINANCIAL_GOALS` `RUN_ANALYSIS`

**默认 entitlement (`account_id='*'`，不含持仓/画像）：**  
`READ_MARKET_DATA` `READ_PUBLIC_RESEARCH` `RUN_ANALYSIS`

**budget：**  
`default`: react 8 / tools 12 / subgraph 60 / request 90  
（删除按 `analysis_type` 六套预算）

**capability 种子（逐行写入，`requires_authenticated_user` 对 portfolio.* / user.* 为 TRUE）：**

| name | adapter | toolset | operations | depends_on | auth_user |
|---|---|---|---|---|---|
| `market.resolve_instrument` | mcp | market_read | READ_MARKET_DATA | {} | F |
| `market.get_realtime_quote` | mcp | market_read | READ_MARKET_DATA | `{market.resolve_instrument}` | F |
| `market.get_historical_prices` | mcp | market_read | READ_MARKET_DATA | `{market.resolve_instrument}` | F |
| `market.get_financial_statements` | mcp | fundamental_read | READ_MARKET_DATA | `{market.resolve_instrument}` | F |
| `market.get_valuation` | mcp | fundamental_read | READ_MARKET_DATA | `{market.resolve_instrument}` | F |
| `market.get_industry_context` | mcp | fundamental_read | READ_MARKET_DATA | `{market.resolve_instrument}` | F |
| `market.get_money_flow` | mcp | market_read | READ_MARKET_DATA | `{market.resolve_instrument}` | F |
| `market.get_news` | mcp | news_read | READ_MARKET_DATA | `{market.resolve_instrument}` | F |
| `research.web_search` | web | news_read | READ_PUBLIC_RESEARCH | {} | F |
| `analysis.run_analysis` | local | planning_compute | RUN_ANALYSIS | {} | F |
| `portfolio.get_current_positions` | java | portfolio_read | READ_PORTFOLIO | {} | T |
| `portfolio.get_account_snapshot` | java | portfolio_read | READ_PORTFOLIO | {} | T |
| `portfolio.get_transaction_history` | java | portfolio_read | READ_PORTFOLIO | {} | T |
| `portfolio.build_current_valuation` | local | portfolio_read | READ_PORTFOLIO | `{portfolio.get_current_positions,portfolio.get_account_snapshot}` | T |
| `user.get_risk_profile` | java | financial_profile_read | READ_PROFILE | {} | T |
| `plugin_probe.run_contract_check` | local | plugin_probe_compute | RUN_ANALYSIS | {} | F |

描述字符串复制现网 `capabilities.py` / plugin_probe 的 description。  
`get_historical_prices` 的 `required_arguments` = `{symbol,lookback_days}`；quote 等 = `{symbol}`；web_search = `{query}`；probe = `{probe_ref,observed_at}`。

**注意：** `portfolio.get_transaction_history` **登记在能力表**，但默认 entitlement **不授** `READ_PORTFOLIO`，且 `portfolio-health` **enabled=false**，因此默认菜单里不会出现。不要从能力表删除它。

**skills：**

| skill_id | enabled | required ops | required caps |
|---|---|---|---|
| `stock-research` | **TRUE** | READ_MARKET_DATA, RUN_ANALYSIS；optional READ_PUBLIC_RESEARCH | M1 行情/财报/估值/行业/资金流/新闻 + resolve + quote + historical + run_analysis；optional web_search |
| `portfolio-health` | FALSE | READ_PORTFOLIO, READ_PROFILE | positions, account_snapshot, build_current_valuation, risk_profile |
| `suitability-evaluation` | FALSE | READ_MARKET_DATA, READ_PORTFOLIO, READ_PROFILE, RUN_ANALYSIS；optional READ_PUBLIC_RESEARCH | 上两行并集 |
| `plugin-contract-probe` | FALSE（EXPERIMENTAL） | RUN_ANALYSIS | plugin_probe.run_contract_check |

**快路径：** 把 `cognitive/semantic_router/catalog.py` 的三条 Route 及全部 utterance、threshold、disposition、response **原样插入** `bdlh_runtime_fastpath_*`。`build_kernel_router()` 改为从 loader 读，删除 `kernel_routes()` 硬编码。

---

## 4. 新契约（代码，不是库表）

新增 `bdlh-runtime-orchestrator/src/bdlh_runtime/cognitive/goal_schema.py`：

```text
RequestedTopic = Literal["news", "money_flow", "industry", "web_research"]

class GoalSpec(BaseModel):
    extra = forbid
    goal_id: str
    objective: str
    requested_topics: list[RequestedTopic] = []
    success_criteria: list[str]
    status: Literal["PENDING", "COVERED", "BLOCKED"] = "PENDING"
    observation_refs: list[str] = []

class UnderstandOutput(BaseModel):
    extra = forbid
    goals: list[GoalSpec]           # min_length=1
    entities: dict                  # names[], time_range? 等
    constraints: list[str]
    missing: list[str]
    needs_external: bool
    # 禁止字段：route, skill_id, analysis_type, plan_steps
```

复合用户问题（对比 + 对照账户）→ **多个 GoalSpec**。每个 Goal 是覆盖单元，**共享同一份 `allowed`**，禁止每 Goal 一张菜单。

新增 `ToolWindow`：

```text
allowed_hash: str
visible_toolsets: list[str]
visible_capabilities: list[str]
expansion_reason: str
generation: int
```

新增 Agent 动作：

```text
CALL_TOOL { capability, arguments }
OPEN_TOOLSET { toolset }
EXPAND_WINDOW {}
FINISH { reason }
```

`OPEN_TOOLSET` / `EXPAND_WINDOW` **不是 Capability**，不经 Adapter。

`GoalCoverage`：对每个 Goal，`success_criteria` 均有对应 SUCCESS Observation 引用 → COVERED；资格不足 → BLOCKED（不编数据）。

---

## 5. 菜单算法（`registry/menu.py`，纯函数，无 LLM）

```text
effective_operations(runtime_id, account_id, enabled_skills)
  = runtime_allowlist
  ∩ ∪(enabled skill declared operations)
  ∩ entitlements(account_id) or entitlements('*')

eligible
  = capabilities where
      enabled
      AND read_only
      AND required_operations ⊆ effective_operations
      AND 属于至少一个 enabled skill 的 required/optional caps

allowed
  = eligible where
      (NOT requires_authenticated_user) OR (authenticated_user_id 非空)
      AND provider 可用（MCP/Java 健康检查失败则该 adapter 的能力暂不入 allowed，记 limitation；不得解释为无资格证）

window(allowed, goals, n_max=20):
  if len(allowed) <= 20: 扁平列出全部
  else: 按 toolset 折叠；用 goals.objective 文本对 toolset.description 打分（可选向量）
        本步展开 top 2–3 组
  对已暴露 capability 做 depends_on 闭包，前置一并进入窗口
  结果 ⊆ allowed
```

向量层：对 `goals[].objective` 与 toolset 描述编码。阈值只用于排序。失败 fail-open。  
**禁止**对用户原句 × capability 做阈值删除。

控制器保证可达：

1. 窗口无合法下一步且仍有 PENDING goal → 展开下一 toolset  
2. 高分组无进展 → **至少一次**完整 `allowed`  
3. 完整 `allowed` 仍不够 → ASK_USER / LIMITED  
4. 禁止因首轮窗口没有某工具就 FINISH  

---

## 6. 逐文件改动

路径均相对 `bdlh-runtime-orchestrator/`，除非注明。

### 6.1 删除或停止作为真源（重写后不得再被启动路径 import 为目录）

| 文件 | 动作 |
|---|---|
| `src/bdlh_runtime/tools/capabilities.py` | **删除** `build_default_capability_registry`、`analysis_types` 字段、`candidates_for`。`CapabilitySpec` 改为从 DB 行构建：增加 `required_operations`、`requires_authenticated_user`、`depends_on`；去掉 `analysis_types`。`ToolsetName` 可改为从 DB 加载的 str，或保留 enum 但启动时与 DB 对账，对不上 fail-fast。 |
| `src/bdlh_runtime/domains/finance/authorization.py` | **删除** `M1_OPERATION_CAPABILITIES` / `M3_*` / `FINANCE_OPERATION_CAPABILITIES` 常量映射。`FinanceCapabilityAuthorizationPolicy.allowed_capabilities` 改为读 `menu.effective_operations` + capability_operation 表。 |
| `src/bdlh_runtime/domains/finance/manifests.py` | Skill 启用、required_capabilities **改为读库**。本文件可留契约字段名常量，但 `enabled_intents` / 能力列表不得再写死。`idempotency_keys` 去掉 `analysis_type`，改为 `request_id` + `instruments` + `goal_ids`。删除 `analysis_type` 相关 input_constraints。 |
| `src/bdlh_runtime/domains/plugin_probe/capability.py` | **删除** `register_plugin_probe_capability` 向内存 Registry 塞硬编码 Spec；探针能力只来自种子。可保留 `PLUGIN_PROBE_CAPABILITY` 字符串常量供测试引用。 |
| `src/bdlh_runtime/tools/requirement_planner.py` | **删除** `REQUIREMENT_POLICIES` 与按 `analysis_type` 的 `plan()`。数据需求改为 Agent 逐步提出，或由 `depends_on` 闭包生成下一步，不再预写清单。 |
| `src/bdlh_runtime/runtime/budgets.py` | **删除** `ANALYSIS_BUDGETS` / `budget_for(analysis_type)`。改为 `budget_for_profile(profile)` 读 `bdlh_runtime_run_budget`。 |
| `src/bdlh_runtime/contracts/route.py` | **删除** `IntentRoute` 三模式（或降为内部调试结构，Graph 不再分支）。 |
| `src/bdlh_runtime/cognitive/semantic_router/catalog.py` | **删除** `kernel_routes()` 硬编码；改为 `load_fastpath_routes(store)`。 |

### 6.2 必须改内容的现网文件

**`src/bdlh_runtime/runtimes/langgraph/agents/query_agent.py`**

- 删除 `QueryIntent.analysis_type`、`symbol` 作为主分类、规则里按「估值/持仓」猜类型。  
- `understand()` 返回 `UnderstandOutput`。  
- Prompt：只输出 §4 schema；明确禁止 route/skill_id/analysis_type；复合题拆多个 GoalSpec。  
- 规则降级：不得猜 analysis_type；无 LLM 时 `needs_external=true`、`goals=[{objective: 原句, success_criteria:["给出有证据的回答"]}]`，`missing=[]`。  
- 删除 `_QUERY_SYSTEM_PROMPT` 中的 analysis_type 枚举。

**`src/bdlh_runtime/runtimes/langgraph/nodes/nodes.py`**

- `understand_request`：写入 `state["goals"]` 等，不再写旧 `intent.analysis_type`。  
- **删除** `route_execution`（关键词切 direct_response / single_capability）。  
- **删除** `_build_data_requirements` 对 planner.plan(analysis_type)。  
- `check_missing_context`：只看 `UnderstandOutput.missing` 与 Goal 的 BLOCKED，不再 `needs_symbol = analysis_type in {...}`。  
- `direct_response_node`：仅服务快路径已结束的情况，或 `needs_external=false`；不根据「什么是」关键词抢答需要实时数字的问题。  
- `_plan_for` / `WorkflowPlan.analysis_type`：见 contracts/workflow.py。

**`src/bdlh_runtime/runtimes/langgraph/graphs/query_graph.py`**

重写边：

```text
receive → understand
  → 若 missing: clarify → understand
  → 若 not needs_external: END（root 走无工具回答）
  → 若 needs_external: build_allowed_menu → END
```

删除节点：`route_execution`、旧 `build_data_requirements`。  
新增：`build_allowed_menu`（调用 `registry.menu`，写入 `state["allowed"]`、`state["tool_window"]`）。

**`src/bdlh_runtime/runtimes/langgraph/graphs/root_graph.py`**

- `route_after_query`：不要读 `intent_route.mode`。改为：无工具回答 / 进 Agent 循环（原 dispatch + market_data_graph）。  
- 删除「有 symbol 就 single_capability 一次 quote」作为理解后的强制快路径。报价快路径仅当 Agent 选了 `get_realtime_quote` 且窗口/闭包已含 resolve。  
- `market_snapshot` 专用 fast_path 节点：改为「当前窗口仅剩 quote 且 resolve 已满足」时的执行优化，**不得**按已删除的 analysis_type 进入。

**`src/bdlh_runtime/runtimes/langgraph/graphs/market_data_graph.py`**

- 删除 `_route_after_market_query` 中 `analysis_type == "market_snapshot"`。  
- ReAct：`choose_next_action` 的候选改为 `state["tool_window"].visible_capabilities`，白名单为 `state["allowed"]`。  
- 预算来自 `state["budget"]`（profile=default），继续执行 `_budget_limit`。  
- 依赖闭包：选 quote 但无 instrument observation → 控制器插入 resolve，不靠相似度。

**`src/bdlh_runtime/runtimes/langgraph/graphs/state.py`**

- 删除/停止使用 `intent.analysis_type`、`intent_route` 作为主路由。  
- 新增：`goals`, `understand`, `eligible`, `allowed`, `tool_window`, `goal_coverage`。  
- `capability_candidates` 改为窗口可见列表。  
- `budget` 注释去掉 analysis_type。

**`src/bdlh_runtime/runtimes/langgraph/agents/research_agent.py`**

- 输入改为 `observations + allowed/window + goals`，删除 `remaining_requirements` 按类型清单。  
- 规则版：按 PENDING goal + depends_on 选下一个未 SUCCESS 的 allowed 能力；全 COVERED 则 FINISH。  
- LLM 版：不限 comprehensive；凡 `needs_external` 均可。输出必须 ∈ 窗口；窗口外降级规则版。  
- 删除 `create_research_agent(..., analysis_type=)`。

**`src/bdlh_runtime/runtimes/shared/analysis_assembly.py`**  
去掉 `analysis_type` 参数；改为按已有 Observation 种类组装。缺数据用 coverage，不用类型桶。

**`src/bdlh_runtime/domain/analysis_engine.py`** 与 **`contracts/analysis.py`**  
删除对 `analysis_type` 字符串分支若仅用于选指标包：改为「有哪些 Observation 就算哪些」；禁止再要求调用方传入 analysis_type。测试 `test_market_snapshot_needs_only_quote` 改为「只有 quote observation 时仍能出快照」。

**`src/bdlh_runtime/contracts/workflow.py`**  
删除 `WorkflowPlan.analysis_type`。

**`src/bdlh_runtime/domains/finance/contracts.py`**

- **删除** `FinancialDomainRequest.analysis_type` 及 SUITABILITY 必须 comprehensive 的校验。  
- Suitability 未启用时仍 `ACTION_NOT_ENABLED`（读库 `skill.enabled`）。  
- `requested_topics` 保留现有四值，作为 Goal 数据主题，**不**再门控 REQUIREMENT_POLICIES。  
- `STOCK_RESEARCH requires exactly one instrument`：对比多标的是本重写要支持的；改为「每个涉及标的的 Goal 必须最终有已解析 instrument」；**允许 instruments 长度 > 1**。这是重写行为变化，需改对应测试。  
- `idempotency` 不再含 analysis_type。

**`src/bdlh_runtime/domains/finance/cognitive_adapter.py`**

- 停止 `_analysis_type(event.message)`。  
- 构造 `FinancialDomainRequest` 时：`authorized_operations` 来自本轮 `effective_operations`（读库），不要写死三件套或按句子分类。  
- 多标的对比：不要先 ASK「你想分析哪只」除非 resolve 歧义。  
- 删除 suitability 关键词抢答可保留未启用提示，但不得把用户塞进 stock-research 假装完成适配性。

**`src/bdlh_runtime/domains/finance/runtime.py`**  
授权改为读库；删除对 `request.financial_intent != STOCK_RESEARCH` 的硬编码前，改为 `loader.skill_enabled`。未启用返回 `ACTION_NOT_ENABLED`。

**`src/bdlh_runtime/domains/finance/planner.py`**  
删除按 toolset×analysis_type 展开。Planner 若仍存在，只做 Domain 内确定性组装，不预写工具链。

**`src/bdlh_runtime/runtime/application.py`**

- 启动：`registry.loader.load(settings.postgres_dsn)`，失败则不要创建 FastAPI app。  
- 删除 `build_default_capability_registry()` 作为生产真源。  
- 删除 `authorized_operations=frozenset({...})` 硬编码，改为 allowlist 表。  
- `create_research_agent(llm, analysis_type=...)` 两行改为单一 Agent。  
- `build_kernel_router()` 注入 DB 快路径。  
- 测试/无 DSN：仅 `environment=local` 且显式 `BDLH_REGISTRY_DSN` 可指向测试库；**禁止**内存默认 15 工具。单测用 fixture 写入临时库或 loader 的 `InMemoryRegistryStore` 由测试插入与种子相同的行。

**`src/bdlh_runtime/runtime/manifest_validation.py`**  
改为校验 **DB 行** 与 Adapter 路由表一致（每个 capability.adapter 在 integrations 有处理器），而不是校验 Python Manifest 列表。

**`src/bdlh_runtime/tools/toolsets.py`**  
`build_default_toolset_registry` 改为从已加载 Registry 派生，禁止第二份描述字典；描述来自 `bdlh_runtime_toolset`。

**`src/bdlh_runtime/tools/__init__.py`**  
去掉对外导出 `build_default_capability_registry` 或将其变为 `load_capability_registry(store)`。

**`src/bdlh_runtime/cognitive/semantic_router/router.py` `selector.py` `encoder.py`**  
算法可留。数据源改 DB。阈值用表内 `score_threshold`。未命中 `None` → fallback 理解，不变。

**`src/bdlh_runtime/cognitive/orchestrator.py`**  
`authorized_operations` 从 allowlist 注入 GuardrailContext，不要构造函数写死。

**`src/bdlh_runtime/config.py`**  
可增加 `registry_dsn`（默认等于 `postgres_dsn`）。生产无 DSN 与现网一样 fail。

**`src/bdlh_runtime/main.py`**  
lifespan 内先 `loader.ensure_schema_and_seed()` 再 `load_and_validate()`。

### 6.3 测试文件（全部去掉 analysis_type 路由假设）

必须改或重写：

- `tests/runtimes/test_agents.py`  
- `tests/graphs/test_react_market_data.py`  
- `tests/graphs/test_root_graph.py`（`direct_response` 仅保留快路径闲聊/知识）  
- `tests/cognitive/test_semantic_router.py`（改从种子库加载）  
- `tests/cognitive/test_finance_cognitive_flow.py`  
- `tests/tools/test_capability_planning.py`（删除 POLICY[analysis_type]）  
- `tests/tools/test_toolsets.py`  
- `tests/tools/test_analysis_capability.py`  
- `tests/contracts/test_foundation_contracts.py`  
- `tests/domains/finance/test_runtime.py`  
- `tests/domains/finance/test_research_builder.py`  
- `tests/domains/finance/test_snapshot_builder.py`  
- `tests/domain/test_analysis_engine.py`  
- `tests/architecture/test_manifest_validation.py`  
- `tests/contracts/test_manifests.py`  
- `tests/runtimes/test_analysis_assembly.py`  
- `tests/api/test_chat_api.py`（知识问答仍无工具）  

新增：

- `tests/registry/test_menu.py`：未开持仓插件时问账户 → allowed 无 portfolio.*；登录不影响 eligible。  
- `tests/registry/test_window.py`：闭包带上 resolve；低分前置不得从 allowed 消失。  
- `tests/cognitive/test_understand_schema.py`：输出含 analysis_type 必须校验失败。  
- `tests/graphs/test_goal_coverage_stop.py`：LLM FINISH 但无 observation → 拒绝结束。

### 6.4 文档（重写时可改，非本 Prompt 强制但建议同 PR）

- `docs/architecture/ADR-010`：注明 Manifest 编译期目录作废，真源为 DB。  
- 00 号架构 / 00 号生产 Prompt 中 `analysis_type` 规划段标记 superseded。  
- **不要**在本任务实现 ADR-016。

---

## 7. application 装配顺序（启动）

```text
1. Settings（POSTGRES_DSN）
2. registry.store.connect
3. execute schema.sql
4. seed.sql（INSERT ... ON CONFLICT DO NOTHING）
5. loader.validate() → ConfigurationError 则 sys.exit
6. MenuService / FastpathRouter 持有只读快照（进程内缓存，热更新非本任务）
7. 再装配 CognitiveOrchestrator、DomainDispatcher、FastAPI
```

测试 fixture：session 级临时 Postgres 或事务回滚；每个测试可 `TRUNCATE` 业务表后重新 seed。

---

## 8. 与现网行为的故意差异（写进 PR 说明）

| 现网 | 重写后 |
|---|---|
| 抽出一个代码 → stock-research 单标的 | 对比两家允许两个 instrument Goal |
| 「什么是」关键词 → 不查数 | 仅快路径 knowledge 过线才无工具；「现在市盈率」进理解且 needs_external=true |
| 有 symbol + market_snapshot → 只调一次 quote | 由 goal 覆盖决定是否只调一次 |
| comprehensive 才 LLM 选工具 | 所有 needs_external 均可 Agent 选，白名单=allowed |
| 持仓关键词 → analysis_type=portfolio_impact | 无类型；无证则 BLOCKED goal |

---

## 9. 明确不要做

- 实现 Deep Research、百炼分流、`research.deep_search`  
- 匿名 `actor_id` / 把 `authenticated_user_id` 改成可选  
- 代码内置工具清单兜底  
- 用户原句向量筛工具当唯一名单  
- 按分数把工具用一遍  
- 拆 stock-research 为多个分析 Skill  
- 理解 JSON 输出 plan_steps / route / analysis_type  
- 双写旧 analysis_type 字段  
- 改 Java 下单/写账户  
- 未经要求 push / 建与任务无关的分支名（分支策略由调用方参数决定）

---

## 10. 验收清单（执行者逐项打勾）

- [ ] `rg "analysis_type" bdlh-runtime-orchestrator/src bdlh-runtime-orchestrator/tests` 无生产引用  
- [ ] `rg "build_default_capability_registry" src` 无生产启动路径  
- [ ] `rg "REQUIREMENT_POLICIES" src` 为零  
- [ ] `rg "kernel_routes" src` 为零或仅测试对照旧行为（应删除）  
- [ ] 空库无 seed → 进程拒绝启动  
- [ ] 默认用户：allowed 含 quote/historical/valuation，**不含** `portfolio.get_current_positions`  
- [ ] 启用 portfolio-health + entitlement READ_PORTFOLIO + 登录 → 持仓进入 allowed  
- [ ] 「谢谢」快路径无工具  
- [ ] 「PE 是什么意思」knowledge 过线无工具  
- [ ] 「现在市盈率多少」+ 已启用研究 → 可只调 valuation 或 quote，有 resolve 闭包  
- [ ] 「对比 A 和 B 并对照账户」无持仓证 → 研究 Goal 可走，账户 Goal BLOCKED，不改判单标的  
- [ ] 未登录问持仓 → ASK 登录，不编持仓  
- [ ] Agent 输出窗口外 capability → Gateway 拒绝  
- [ ] FINISH 无 observation → 控制器拒绝  
- [ ] 现有非路由测试（observation normalizer、MCP adapter、JWT）仍绿  

---

## 11. 完成报告格式

执行者交付时必须包含：

1. 文件变更列表（新增 / 修改 / 删除）  
2. `schema.sql` / `seed.sql` 已执行的证据  
3. `rg analysis_type` 结果  
4. 测试命令与结果（`pytest` 范围）  
5. 未做项（必须与 §9 一致）  
6. 行为差异表（对照 §8）

未完成 §10 不得声称重写完成。不得把 Deep Research 或匿名入口塞进本次 PR。
