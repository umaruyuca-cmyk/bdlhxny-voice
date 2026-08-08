# StockWise 全新股票分析系统
# 统一开发实施 Prompt

> 版本：v2.3  
> 状态：当前唯一有效的开发 Prompt  
> 目标目录：`F:\privateskill\StockWise\stockwise-analysis`  
> 适用范围：Python LangGraph 流程服务、MCP 数据接入、Java 用户数据接入、可替换的分析能力接入  
>
> v2.1 变更（基于 MCP 可用性验证与架构复核）：  
> - §2.3 新增 MCP 云端部署形态与数据域风险分层；  
> - §4 新增 Phase 2.5（Node Skill 服务化与纯分析改造）为强制前置步骤；  
> - §7.1 交易日历改为 Python 本地计算，不再作 MCP 能力；  
> - §8 预算改为按 analysis_type 分档，comprehensive 总预算放宽至 240s；  
> - §10.2 AnalysisInput 新增 overseas_context；  
> - §13 新增数据源可用性验证与 Skill 重构步骤；  
> - §16 新增数据源可用性验证报告、Skill 服务化说明与 stock-wrapper 退役说明。 
>
> v2.2 变更（stock-wrapper 彻底退役 + 同源备份策略澄清 + 逃生阀机制）：  
> - §2.2 / §3 明确 stock-wrapper 不进运行时，代码保留仅作离线回归测试，不作为数据备份源；  
> - §7.2 澄清"同源不构成高可用备份"：两个 MCP 连续失败时返回 `LIMITED`，**不得调用 Skill 补查数据**；是否接入第三方异构备份由 Phase 2 实测决定（逃生阀），不在未验证前预设；  
> - §10.2 降级策略新增"已知不可用"标记机制，如实向用户说明数据源失效，不编造。 
>
> v2.3 变更（分析能力实现方式后置 + 开发边界明确）：  
> - 不再把 Node.js Skill 服务化作为强制前置，先使用 Python 分析能力跑通主流程；  
> - `AnalysisInput` / `AnalysisResult` 作为稳定契约，分析能力可以是 Python 模块、独立进程或后续 Skill 服务；  
> - 补充 MCP 传输配置、ReAct 执行矩阵、交易日历边界、fixture 离线回归和分页契约；  
> - 修正数据源验证步骤引用，统一以 §13 第 7 步后的验证说明为准。 

---

## 1. 你的角色

你是一名高级 Python、LangGraph、LangChain、MCP 和 Agent 系统工程师，负责在现有工作区中构建全新的股票分析流程服务。

这不是对旧 Java Agent 的局部修补，也不是继续扩展旧的 `stock-wrapper` 查询接口，而是建立独立的 Python 分析系统。

---

## 2. 当前状态与开发基线

### 2.1 已完成内容

以下工作视为已经完成，不要重复执行：

- Python 项目目录已建立；
- `stockwise-analysis/src/stockwise_analysis` 作为唯一 Python 包入口；
- 架构、复核意见和历史设计文档已经归档；
- 旧 Java、旧 stock-wrapper、前端和数据库暂不删除；
- 当前系统仍处于新旧系统并行开发阶段。

### 2.2 本 Prompt 解决的问题

后续系统统一采用以下职责边界：

```text
Python LangGraph       统一流程控制、Agent、ReAct 和状态管理
MCP 服务               查询外部市场数据
Java Data API          查询用户持仓、账户和用户配置
Market Data Gateway    统一管理两个 MCP，不让 Agent 直接管理 MCP
Analysis Capability    基于输入数据完成分析、计算和总结，具体部署形态后置决定
大模型                 问题理解、单步决策、补充询问和最终表达
```

最重要的变化：

> Skill 不再查询数据。Skill 只能接收标准化数据，并基于输入完成分析计算和总结。

### 2.3 MCP 与 Skill 部署形态

两个 MCP 以远程 MCP 服务部署，Python LangGraph 通过 MCP Client 接入。两个服务的传输协议和端点必须通过配置区分，不得假设它们使用同一种 HTTP 传输方式。

分析能力暂不绑定 Node.js。第一阶段优先以 Python Domain/Analysis Engine 形式实现，跑通完整流程后，再根据复用性、性能、依赖隔离和部署成本评估是否保留现有 Node Skill、改为独立服务或迁移为 Python 模块。`stock-wrapper` 不再属于新架构的运行时组件。

两个 MCP 的连接配置必须显式区分传输类型和端点，例如：

```yaml
mcp:
  akshare_one:
    transport: streamable_http
    endpoint: ${AKSHARE_ONE_MCP_ENDPOINT}
    timeout_seconds: 20
    token: ${AKSHARE_ONE_MCP_TOKEN}
  cn_financial:
    transport: sse
    endpoint: ${CN_FINANCIAL_MCP_ENDPOINT}
    timeout_seconds: 20
    token: ${CN_FINANCIAL_MCP_TOKEN}
```

实际传输类型以云端部署配置和握手测试结果为准，不得在代码中假设两个 MCP 使用同一种传输方式。

云端部署可规避本机的系统代理与 TLS 指纹问题，但引入两个新约束：

- 本地 ↔ 云端的往返延迟（RTT）需计入 §8 的运行预算；
- 云服务器 IP 段可能被数据源风控，**不假设 MCP 全量可用，以云端实测可达性为准**。

数据域风险分层（当前环境观察，必须通过云端部署重新验证）：

| 数据域 | 底层数据接口域名 | 风险等级 | 说明 |
|---|---|---|---|
| 财务报表、北向资金、宏观 | `datacenter-web.eastmoney.com` | 低 | 稳定，几乎不被风控 |
| 实时行情 | `push2.eastmoney.com` / `82.push2` | 高 | push2 系域名易被 TLS 指纹/IP 段风控 |
| 历史 K 线 | `push2his.eastmoney.com` | 高 | 同上，且存在间歇性失败 |
| 板块、个股资金流 | `17.push2.eastmoney.com` | 高 | 同上 |

因此 Phase 2 接入 MCP 后，首要工作是产出"能力 × 可用性"实测验证表（见 §13 第 7 步后的验证说明与 §16 交付物），据此校准 §7.2 路由策略，而非直接信任 MCP README 声称的能力。

---

## 3. 总体业务流程

```text
用户问题
  ↓
Root Graph（根流程）
  ↓
问题理解与上下文检查
  ↓
数据需求规划
  ↓
Market Data Acquisition Graph（市场数据获取子图）
  ├── Market Data Gateway → akshare-one-mcp
  ├── Market Data Gateway → cn-financial-mcp
  └── Java Data Tool → 用户持仓和账户数据
  ↓
Observation Normalizer（观测结果标准化）
  ↓
AnalysisInput 组装
  ↓
Analysis Capability Adapter
  ↓
Python Analysis Engine（第一阶段默认实现）
  └── 可选：后续接入独立 Skill 服务
  ↓
AnalysisResult 校验
  ↓
Summary Model（总结模型）
  ↓
用户确认或最终回答
```

---

## 4. 开发阶段

### Phase 0：Python Runtime 与基础契约

先实现可运行的 Python 流程骨架：

- 项目启动入口；
- 配置管理；
- RootState、ChildState 和运行上下文；
- WorkflowPlan 和 TaskSpec；
- Observation、错误和预算契约；
- LangGraph Root Graph；
- Checkpointer；
- `interrupt()` 与 `Command(resume=...)` 恢复；
- SSE 事件流；
- Tool Registry 和 Tool Runtime；
- 一个只读 Mock Tool；
- FastAPI API；
- 最小测试集。

本阶段可以使用 Mock 数据，但不得把 Mock 逻辑写死到领域计算层。

### Phase 1：问题理解与数据需求规划

实现：

- 用户问题结构化解析；
- 标的、市场、时间范围和分析类型识别；
- 是否涉及用户持仓的识别；
- 缺少关键条件时触发中断；
- 生成 `DataRequirement`；
- 生成初始 `WorkflowPlan`。

本阶段不调用 Skill，也不允许模型直接调用任意 MCP。

### Phase 2：MCP Gateway 与市场数据获取

接入两个已经可以调用的 MCP 服务：

- `akshare-one-mcp`；
- `cn-financial-mcp`。

实现 MCP Adapter、工具统一注册、主备路由、超时、重试、Observation 标准化和有界 ReAct。

本阶段接入后必须先跑"能力 × 可用性"验证（见 §13 第 7 步后的验证说明），用云端实测结果校准 §7.2 路由表，不得直接信任 MCP README。

### Phase 2.5：分析能力实现方式评估与最小实现

> 这是 Phase 2 与 Phase 3 之间的强制步骤，但不要求使用 Node.js。目标是先建立稳定的分析契约和可测试的本地分析实现，不让旧 Node Skill 或 stock-wrapper 阻塞主流程。

本阶段实现：

- **定义纯分析接口**：实现 `analyze(input: AnalysisInput) -> AnalysisResult`，只消费已标准化输入，不根据 symbol 查询数据；
- **第一阶段使用 Python 实现**：分析指标、风险计算和规则结论先放入 Python Domain/Analysis Engine，作为默认 `AnalysisCapability`；
- **保留可替换边界**：`AnalysisCapabilityAdapter` 必须允许未来接入 Python 子进程、Node Skill 或其他独立服务，但当前不得要求实现 HTTP Skill 服务；
- **切断旧数据耦合**：如果继续复用现有 Node Skill 代码，必须扫描其全部 `src/data/*`，解除对 `src/analysis/*` 和 HTTP 请求工具的依赖；data 层只保留 DTO、类型和标准化逻辑；
- **旧 CLI 和 stock-wrapper 仅作迁移遗留**：不得进入 Python 生产链路；只有使用固定 fixture/replay 数据时才允许做离线回归，不得以真实行情接口作为回归前提；
- **契约校验保留并升级**：补充 `analysis_id`、`analysis_type`、`data_quality`、`provenance`、`methodology_version` 和 `schema_version`。

验收标准：Python 分析能力在**断网**（无任何行情接口可达）情况下，喂入固定 `AnalysisInput` 仍能产出结构完整的 `AnalysisResult`；生产链路中不存在 stock-wrapper 进程和调用。若保留旧 Node Skill，其代码必须满足以下静态检查：`src/data/*` 不得引用 `src/analysis/*` 或 HTTP 请求工具。

### Phase 3：分析能力接入

通过统一的 `AnalysisCapabilityAdapter` 接入第一阶段的 Python Analysis Engine：

- Python 负责组装 `AnalysisInput`；
- 分析能力只消费输入数据并返回 `AnalysisResult`；
- Python 校验结果并继续后续流程；
- 大模型根据结构化结果生成最终回答。

Node Skill 是否继续使用，待主流程跑通后单独评估，不得作为本阶段阻塞条件。

### Phase 4：持仓、策略和回测扩展

后续再接入：

- Java 持仓服务；
- 组合分析；
- 策略设计；
- 回测引擎；
- 知识库和记忆；
- 用户确认后的知识入库。

本 Prompt 只要求预留边界，不提前实现真实交易、下单、撤单和券商执行。

---

## 5. Python 代码目录

统一使用以下目录，不得再创建第二套 `app/` 或其他 Python 入口：

```text
stockwise-analysis/
├── pyproject.toml
├── README.md
├── tests/
└── src/stockwise_analysis/
    ├── main.py
    ├── config.py
    ├── api/
    │   ├── routes.py
    │   ├── schemas.py
    │   └── sse.py
    ├── runtime/
    │   ├── application.py
    │   ├── context.py
    │   ├── budgets.py
    │   ├── errors.py
    │   └── recovery.py
    ├── graph/
    │   ├── state.py
    │   ├── root_graph.py
    │   ├── query_graph.py
    │   ├── market_data_graph.py
    │   └── nodes.py
    ├── contracts/
    │   ├── workflow.py
    │   ├── observation.py
    │   ├── data_requirements.py
    │   ├── analysis.py
    │   └── events.py
    ├── tools/
    │   ├── registry.py
    │   ├── runtime.py
    │   ├── models.py
    │   ├── market_data_gateway.py
    │   ├── java_data_adapter.py
    │   └── mock_tools.py
    ├── mcp/
    │   ├── client.py
    │   ├── adapter.py
    │   ├── registry.py
    │   └── routing_policy.py
    ├── skill/
    │   ├── adapter.py
    │   ├── registry.py
    │   └── validator.py
    ├── agents/
    │   ├── query_agent.py
    │   ├── research_agent.py
    │   └── summary_model.py
    ├── observation/
    │   ├── normalizer.py
    │   ├── quality.py
    │   └── provenance.py
    └── domain/
        ├── indicators.py
        ├── risk.py
        ├── calculations.py
        └── trading_calendar.py
```

目录职责界定（避免 `mcp/` 与 `tools/market_data_gateway.py` 重复造两套路由）：

- `mcp/` 负责底层连接与原始工具适配（`client.py` 连接管理、`adapter.py` MCP→Tool 转换、`registry.py` 允许的 MCP 清单、`routing_policy.py` 主备/超时/重试策略）；
- `tools/market_data_gateway.py` 只负责把 §7.1 的 8 个统一能力暴露给 Agent，编排"统一能力 → 哪个 MCP"的调度，不碰连接细节；
- 两层之间单向调用：`gateway → mcp/`，gateway 不直接持有 MCP 连接；
- `domain/trading_calendar.py` 负责交易日历的本地确定性计算（见 §7.1 说明）。

---

## 6. LangGraph 流程

### 6.1 Root Graph

```text
receive_request
  ↓
understand_request
  ↓
check_missing_context
  ├── 缺少条件 → interrupt_for_clarification
  │                 ↓
  │             resume_request
  └── 条件完整
          ↓
build_data_requirements
          ↓
market_data_acquisition_graph
          ↓
load_portfolio_context（按需）
          ↓
assemble_analysis_input
          ↓
invoke_stockwise_skill
          ↓
validate_analysis_result
          ↓
compose_final_response
          ↓
user_confirmation（按需）
          ↓
finish
```

### 6.2 Market Data Acquisition Graph

```text
build_query_plan
  ↓
select_next_data_action
  ↓
execute_market_tool
  ↓
normalize_observation
  ↓
evaluate_data_sufficiency
  ├── 数据完整 → end
  ├── 缺少数据 → select_next_data_action
  ├── 主数据源失败 → invoke_fallback_source
  ├── 数据冲突 → resolve_data_conflict
  └── 关键数据不可用 → LIMITED 或 interrupt
```

外层 Graph 必须控制 Tool 执行、Observation 追加、预算扣减、失败处理和结束条件。Agent 只负责输出下一步结构化动作。

---

## 7. MCP Gateway 设计

### 7.1 统一能力名称

Agent 只能看到统一能力，不直接看到两个 MCP 的原始工具名：

```text
market.resolve_instrument
market.get_realtime_quote
market.get_historical_prices
market.get_financial_statements
market.get_valuation
market.get_industry_context
market.get_money_flow
market.get_news
```

> 交易日历**不作为 MCP 能力暴露**。两个 MCP 均无真正的交易日历工具（`akshare-one` 的 `get_time_info` 只返最近一个交易日；`cn-financial` 的 `get_financial_calendar` 是财报披露日历）。交易日历由 Python `domain/` 层通过 `TradingCalendarProvider` 统一提供；本地日历库和官方交易日历缓存作为实现，必须经过 A 股调休、补班和特殊交易日测试。若本地规则无法覆盖，应接入独立交易日历数据源，不允许 Skill 或 MCP 查询逻辑隐式补充。

### 7.2 路由策略

> 本表为云端部署后的**初始默认值**。Phase 2 接入后必须用"能力 × 可用性"实测结果（§13 第 7 步后的验证说明）校准，校准后的版本作为交付物归档（§16）。

| 统一能力 | 默认源 | 异构备份 | 数据域风险 |
|---|---|---|---|
| 标的搜索 | `cn-financial-mcp` | — | 低 |
| 实时行情 | `cn-financial-mcp` | `akshare-one-mcp` | 高（push2 系） |
| 原始历史 K 线 | `cn-financial-mcp`（禁用其指标参数） | `akshare-one-mcp`（同样禁用指标） | 高（push2his） |
| 财务报表 | `cn-financial-mcp` | `akshare-one-mcp` | 低（datacenter，稳定） |
| 估值、行业、资金流 | `cn-financial-mcp` | — | 中 |
| 新闻和公告 | `cn-financial-mcp` | `akshare-one-mcp` | 低 |

三条强制约束（v2.2）：

> `stock-wrapper`、Node Skill 查询端点和旧 `/api/v1/*` 均不属于新生产链路，**不作为数据备份源**。两个 MCP 连续失败时，不得调用 Skill 补查数据，必须返回结构化失败、`PARTIAL` 或 `LIMITED`，并在 limitations 中如实说明数据源失效（见 §11 逃生阀）。

1. **同源不构成高可用备份**。两个 MCP 均基于 akshare，数据源、fallback 链和被风控方式可能相同——主源挂时备源可能同时挂。两个 MCP 连续失败时，`MarketDataGateway` 必须返回结构化失败或 `LIMITED`，**不得调用 Skill 补查数据**。后续如需真正异构备份，应接入独立的第三方市场数据服务（如腾讯 `web.ifzq.gtimg.cn`），并通过新 Adapter 接入；**是否接入，由 Phase 2 实测验证结果决定（见 §11 逃生阀），不在未验证前预设**。
2. **两个 MCP 不能同时作为同一字段的并行默认源**。只有在数据校验或冲突分析场景下，才允许主动调用第二数据源。
3. **`akshare-one-mcp` 的历史 K 线不是纯原始数据**。它的 `get_hist_data` 会在取数时计算 SMA/MACD/RSI/BOLL 等指标（`indicators_list` 参数）。调用时**必须显式传空 indicators**，且其预计算指标最多作为校验数据，不得作为默认最终结论（与 §10.5 计算责任一致）。

每次调用必须记录：

- MCP 名称；
- 统一工具名称；
- 原始工具名称；
- 请求参数；
- 请求时间；
- 数据时间；
- 响应耗时；
- 是否使用备用源；
- 是否发生字段冲突。

### 7.3 Java 数据 Tool

通过统一 Tool 接口调用 Java API：

```text
portfolio.get_current_positions
portfolio.get_account_snapshot
portfolio.get_transaction_history
user.get_risk_profile
```

Java 返回结果同样必须转换为 Observation，不允许 Graph 节点直接拼接 Java 原始 JSON。

---

## 8. ReAct 规则与运行预算

ReAct（推理与行动循环）只用于市场数据获取子图，不进入分析能力内部。非所有分析类型都启动 ReAct，必须按以下执行矩阵选择路径：

- `market_snapshot`：确定性快路径，不启动 Agent/ReAct；
- `technical`、`fundamental`、`valuation`：优先固定数据计划，遇到缺失字段、分页或主源失败时才允许有限自适应；
- `portfolio_impact`：在 Java 用户数据和市场数据依赖不完整时允许有限 ReAct；
- `comprehensive`：允许完整但有界的 ReAct。

每轮只生成一个动作：

```json
{
  "action": "get_historical_prices",
  "arguments": {
    "symbol": "600000",
    "period": "daily",
    "lookback_days": 120
  },
  "reason": "技术分析需要历史价格序列"
}
```

允许调用的工具只能是只读查询工具，禁止下单、撤单、写库和删除操作。

预算按 `analysis_type` 分档配置（云端 MCP 调用需叠加往返延迟）：

| analysis_type | ReAct 轮数上限 | Tool 调用上限 | 子图预算 | 总请求预算 |
|---|---|---|---|---|
| `market_snapshot` | 2 | 3 | 25s | 40s |
| `technical` | 4 | 5 | 45s | 70s |
| `fundamental` | 5 | 7 | 55s | 90s |
| `valuation` | 4 | 5 | 45s | 70s |
| `portfolio_impact` | 6 | 8 | 60s | 100s |
| `comprehensive` | 10 | 14 | 150s | 240s |

公共约束：

- 单轮模型决策：10 秒；
- 单个 MCP Tool：20 秒（含云端往返延迟）；
- 单个 Java Tool：10 秒；
- 主源失败后最多切换 1 次同源备用源；连续失败则将对应数据维度标记为不可用，并根据分析类型返回 `PARTIAL` 或 `LIMITED`；
- 财报类分页拉取若超过单 Tool 超时，应支持分页续传而非整体失败；分页请求必须携带 `page_token`、`page_size`、`source_request_id`，并记录已完成页，恢复时不得重复写入。

只有 `comprehensive` 进入完整 ReAct；其他类型按照上面的有限自适应规则执行。超出预算必须停止，并输出 `LIMITED` 结果，说明未获取到的数据和未完成的分析维度。

---

## 9. Observation 契约

```python
class Observation(BaseModel):
    observation_id: str
    dimension: str
    subject: str
    facts: list
    source_name: str
    source_type: str
    observed_at: str
    data_as_of: str | None
    quality: str
    limitations: list[str]
    raw_reference: str | None
```

MCP、Java Tool 和 Skill 的外部结果都必须经过统一标准化。未经标准化的原始 JSON 不得直接进入最终 Prompt。

---

## 10. 分析能力契约（可选 Skill）

### 10.1 调用方式

第一阶段默认在 Python Analysis Engine 中直接调用纯函数或本地服务接口：

```python
result = analysis_capability.analyze(analysis_input)
```

LangGraph 通过 `AnalysisCapabilityAdapter` 调用，不在节点中硬编码具体实现。后续如果评估决定把分析能力部署为独立 Skill 服务，再由 Adapter 封装 HTTP、进程或其他通信细节；当前不要求实现 Node HTTP 服务。

若未来选择 HTTP 服务，推荐沿用以下兼容契约：

```http
POST /api/v2/analyze
Content-Type: application/json
```

### 10.2 AnalysisInput

```python
class AnalysisInput(BaseModel):
    schema_version: str
    analysis_id: str
    analysis_type: str
    instrument: InstrumentRef
    realtime_quote: RealtimeQuote | None
    historical_prices: list[HistoricalBar]
    financial_data: FinancialBundle | None
    valuation_data: ValuationBundle | None
    industry_context: IndustryContext | None
    news_context: list[NewsItem]
    portfolio_context: PortfolioContext | None
    overseas_context: OverseasContext | None
    data_quality: DataQuality
    provenance: list[ProvenanceRecord]
    methodology_version: str
```

上述类型必须在 Python 和可选 Skill 实现之间共享，或通过 JSON Schema 固化。所有数据块至少包含 `as_of`、`source`、`retrieved_at` 和 `quality_status`；禁止使用无法追溯来源的裸 `dict` 作为核心契约。

核心类型的最低字段要求：

| 类型 | 必填字段 |
|---|---|
| `InstrumentRef` | `symbol`、`name`、`market`、`exchange`、`instrument_type` |
| `DataQuality` | `completeness`、`freshness`、`quality_status`、`known_unavailable` |
| `ProvenanceRecord` | `source`、`tool`、`request_id`、`as_of`、`retrieved_at`、`fallback_used` |
| 分页信息 | `page_token`、`page_size`、`source_request_id`、`completed_pages` |

支持的 `analysis_type`：

```text
market_snapshot
technical
fundamental
valuation
portfolio_impact
comprehensive
```

分析类型只决定分析能力使用哪些已经提供的数据，不代表分析能力自己查询数据。

> `overseas_context`（外围面，纳斯达克/恒生科技等海外指数）是现有 Skill 的分析维度。**两个 MCP 均不覆盖海外指数数据**，该字段必须由后续独立数据源补充；在数据来源落实前，`comprehensive` 分析的外围面标记为 `PARTIAL`，不得由 Skill 或其他旧接口自行查询或编造。

### 10.3 分析能力禁止事项

- 禁止访问 MCP；
- 禁止访问 Java API；
- 禁止访问数据库；
- 禁止访问行情接口；
- 禁止根据股票代码自行补充数据；
- 禁止在内部启动 ReAct；
- 禁止决定下一步调用哪个工具。

### 10.4 AnalysisResult

```python
class AnalysisResult(BaseModel):
    schema_version: str
    analysis_id: str
    status: str
    facts: list
    calculated_indicators: dict
    signals: list
    risk_flags: list
    conclusions: list
    limitations: list
    data_quality: DataQuality
    provenance: list
    methodology_version: str
```

状态至少包括：

```text
SUCCESS / PARTIAL / LIMITED / FAILED
```

### 10.5 计算责任

MCP 默认返回原始数据，Skill 或 Python Domain 层负责计算：

```text
OHLCV
  → MA / EMA / MACD / RSI / ATR
  → 波动率 / 最大回撤 / 支撑阻力
  → 技术信号 / 风险标记 / 分析结论
```

必须记录指标参数、复权方式、时间范围、算法版本，并防止未来函数。MCP 预计算指标最多作为校验数据，不作为默认最终结论。

---

## 11. 错误、降级和中断

### MCP 失败

1. 记录失败原因；
2. 判断是否允许切换备用源；
3. 备用调用成功则继续并记录来源变化；
4. 备用调用失败则标记对应 Observation 无效；
5. 不允许模型编造缺失数据。

### 数据不足

- 缺少标的或时间范围：使用 `interrupt()` 请求用户补充；
- 非关键数据缺失：继续并标记 `PARTIAL`；
- 关键数据缺失：输出 `LIMITED`；
- 外围面（海外指数）数据缺失：两个 MCP 均不覆盖，继续并标记 `PARTIAL`，在 limitations 中说明"外围面数据未获取"，不得编造；
- 数据源冲突：保留两个 Observation，进入冲突处理节点；
- 无法判断冲突：停止生成确定性结论。

### 逃生阀（同源失效处置）

两个 MCP 同源，对同一数据域（尤其 push2 系的实时行情、历史K线）可能同时失效。此时：

1. 将该数据域标记为"**已知不可用**"，写入本次运行的 `data_quality`；
2. 在 `AnalysisResult.limitations` 中如实说明"行情数据当前因数据源问题不可获取，以下分析基于截至 X 时的数据"；
3. 不得调用 Skill、stock-wrapper 或旧 `/api/v1/*` 补查，不得编造；
4. Phase 2 实测验证（见 §13 第 7 步）若发现某数据域长期不可用，应据此评估是否接入独立的第三方市场数据服务作为真正异构备份——**是否接入由实测数据决定，不在未验证前预设**。

### 分析能力失败

只允许 `AnalysisCapabilityAdapter` 层进行有限重试或返回结构化失败，不允许分析能力自己重新查询数据。若使用 Python 本地实现，则记录异常并返回 `FAILED`；若未来使用独立 Skill 服务，则记录超时、请求 ID 和服务健康状态。

---

## 12. API 与事件流

至少提供：

```text
POST /api/v1/agent-runs
GET  /api/v1/agent-runs/{run_id}
GET  /api/v1/agent-runs/{run_id}/events
POST /api/v1/agent-runs/{run_id}/resume
GET  /api/v1/health
```

事件至少包括：

```text
run_started
node_started
model_decision
tool_started
tool_finished
observation_created
fallback_triggered
skill_started
skill_finished
interrupt_created
run_finished
run_failed
```

事件必须记录 `run_id`、`thread_id`、节点名、工具名、耗时、状态和错误信息，支持前端追踪整个执行过程。

---

## 13. 必须完成的开发内容

按以下顺序实现：

1. 完成 Python 基础 Runtime、配置和启动入口；
2. 完成 RootState、Observation、WorkflowPlan、DataRequirement、AnalysisInput、AnalysisResult；
3. 完成 Checkpointer、interrupt/resume 和事件流；
4. 完成 Tool Registry、Tool Runtime 和 Mock Tool；
5. 完成 Root Graph 和 Query Graph；
6. 完成 MCP Client、MCP Adapter 和 MarketDataGateway；
7. 接入两个 MCP 并完成统一路由；
8. 完成 Observation 标准化和数据质量检查；
9. 完成市场数据获取子图和有界 ReAct；
10. 完成 Java Data Tool Adapter；
11. **完成第一版 Python Analysis Engine**（Phase 2.5）：实现纯 `analyze(AnalysisInput) -> AnalysisResult`，切断分析逻辑对外部查询的依赖，移除 stock-wrapper 生产依赖；
12. 完成 `AnalysisCapabilityAdapter`，默认调用 Python Analysis Engine，并预留未来接入独立 Skill 服务的实现；
13. 完成 Skill 输出校验和最终总结节点；
14. 完成异常、超时、降级、数据冲突和恢复测试；
15. 更新 README 和运行配置。

> 第 7 步接入 MCP 后，**必须先跑"能力 × 可用性"验证**：逐个调用两个 MCP 的关键工具（实时行情、历史 K 线、三大报表、北向资金、板块、新闻），记录可达性、平均耗时、是否触发 fallback、是否命中 §2.3 的高风险域名。验证结果用于校准 §7.2 路由表，并作为 §16 的交付物归档。未通过验证的能力不得作为默认数据源。

---

## 14. 明确禁止的实现方式

- 不允许 Skill 内部查询任何外部数据；
- 不允许 Agent 直接管理两个 MCP 连接；
- 不允许两个 MCP 的重复工具同时暴露给模型；
- 不允许未经标准化的 MCP 原始响应直接交给 Skill；
- 不允许使用无限循环 ReAct；
- 不允许让大模型替代确定性指标和风险计算；
- 不允许在本阶段接入真实下单、撤单或交易执行；
- 不允许因为数据缺失编造行情、财务指标或结论；
- 不允许修改旧 Java Agent 来绕过新 Python 流程；
- 不允许创建第二套 Python 应用目录或入口。

---

## 15. 验收场景

### 场景一：综合市场分析

必须完成：

```text
用户问题
 → 问题理解
 → 数据需求规划
 → MCP 查询
 → Observation 标准化
 → 分析能力计算
 → AnalysisResult 校验
 → 大模型最终回答
```

### 场景二：涉及当前持仓

必须能够同时调用：

```text
Java Portfolio Tool + Market Data Gateway + Analysis Capability
```

并输出标的对用户当前持仓的影响。

### 场景三：主 MCP 失败

必须能够自动切换备用 MCP，并在事件流和最终结果中记录数据源变化。

### 场景四：数据不足

必须能够触发 `interrupt()` 请求用户补充，或返回 `LIMITED`，不得生成虚假确定性结论。

### 场景五：分析能力不可用

必须返回结构化错误、运行轨迹和失败原因，不得退化为让分析能力自己查询数据。若使用 Python 本地实现，则返回 `FAILED`；若未来使用独立 Skill 服务，则记录服务超时、请求 ID 和健康状态。

---

## 16. 最终交付报告

完成后必须输出：

- 新增和修改文件清单；
- 运行方式和环境变量清单；
- LangGraph 节点及状态说明；
- MCP 统一工具和路由表；
- **数据源可用性验证报告**（能力 × MCP × 底层域名 × 可达性 × 平均耗时 × 是否触发 fallback × 命中的风险等级），以及据此校准后的最终路由表；
- **分析能力实现说明**（Phase 2.5）：Python Analysis Engine 的接口、数据依赖、断网 fixture 测试结果，以及 stock-wrapper 生产依赖移除结果；
- `AnalysisInput` / `AnalysisResult` 请求与响应示例；如后续选择独立 Skill，再补充其服务部署和 `/api/v2/analyze` 说明；
- 事件流示例；
- 测试命令和测试结果；
- 未实现内容；
- 已知风险（含云端 IP 段风控、外围面数据缺失、同源备份失效等）；
- 后续开发建议。

最终执行原则：

> 先建立可恢复、可追踪、可测试的 Python 流程，再接入 MCP 和分析能力；MCP 负责取数，分析能力负责计算，LangGraph 负责统一编排。Node Skill 是否保留，待主流程跑通后再决定。
