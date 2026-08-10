# StockWise 全新股票分析系统
# 统一开发实施 Prompt（LangGraph + Mem0 主版本）

> 版本：v3.1  
> 状态：当前唯一有效的开发 Prompt  
> 目标目录：`F:\privateskill\StockWise\stockwise-analysis`  
> 对应架构：[21-全新股票分析系统-架构设计v2.md](../architecture/21-全新股票分析系统-架构设计v2.md)（v3.1）  
> 适用范围：Python LangGraph 主版本流程服务、MCP 数据接入、Mem0 记忆层、Java 用户数据接入、可替换分析能力接入  
>
> **本 Prompt 只覆盖主版本（LangGraph + Mem0）**。Letta 对比版是架构文档 Phase 3 的事，待主版本稳定后单独写 Prompt，不在本文范围内。
>
> v3.1 变更（对齐双 runtime 架构 + MCP 实测校准 + Mem0 记忆层）：
> - 代码目录从 `graph/` 平铺改为 `runtimes/langgraph/` 分层，预留 `runtimes/shared/` 契约；
> - 新增 Mem0 记忆层设计：首尾读写边界、`memory/base.py` 抽象、工程约束（内部 LLM/降级）；
> - 新增 ContextBuilder 设计：LangGraph 版每轮 7 块上下文组装；
> - MCP 路由表换为 **2026-08-06 实测校准版**：akshare-one 的 `source=xueqiu/sina` 即异构备份，无需外接第三方；
> - 补传输协议差异（SSE vs Streamable HTTP）、参数 schema 差异（interval vs period）、服务端吞错坑（error:true）；
> - 保留 v2.3 有效设计：分析能力后置（Python 先行）、分页契约、ReAct 执行矩阵、预算分档、逃生阀。

---

## 1. 你的角色

你是一名高级 Python、LangGraph、MCP 和 Agent 系统工程师，负责在现有工作区中构建全新的股票分析流程服务（主版本：LangGraph + Mem0）。

这不是对旧 Java Agent 的局部修补，也不是继续扩展旧的 `stock-wrapper` 查询接口，而是建立独立的 Python 分析系统。Letta 对比版本不在本 Prompt 范围内。

---

## 2. 当前状态与开发基线

### 2.1 已完成内容

以下工作视为已经完成，不要重复执行：

- Python 项目目录已建立；
- `stockwise-analysis/src/stockwise_analysis` 作为唯一 Python 包入口；
- 架构设计 v3.1 已定稿，为本 Prompt 的上位文档；
- 旧 Java、旧 stock-wrapper、前端和数据库暂不删除；
- 两个金融 MCP 已云端部署并完成可用性实测（见 §7.0）；
- 当前系统仍处于新旧系统并行开发阶段。

### 2.2 本 Prompt 解决的问题

主版本统一采用以下职责边界：

```text
LangGraph (runtimes/langgraph/)  统一流程控制、有界 ReAct、状态管理、ContextBuilder
Mem0 (memory/)                   记忆层，仅首尾读写，不污染主流程确定性
MCP 服务                          查询外部市场数据（两个 MCP，传输协议不同）
Java Data API                    查询用户持仓、账户和用户配置
Market Data Gateway              统一管理两个 MCP，不让 Agent 直接管理 MCP
Analysis Capability              基于输入数据完成分析、计算和总结，部署形态后置
大模型                            问题理解、单步决策、补充询问和最终表达
```

最重要的边界：

> 分析能力不再查询数据。它只接收标准化数据，并基于输入完成分析计算和总结。
> Mem0 仅在对话首尾被读写，ReAct 循环中不碰记忆。

### 2.3 部署形态

两个 MCP 以远程服务部署，Python LangGraph 通过 MCP Client 接入。**两个服务传输协议不同，必须分别配置**：

```yaml
mcp:
  akshare_one:
    transport: streamable_http       # Streamable HTTP
    endpoint: ${AKSHARE_ONE_MCP_ENDPOINT}   # http://118.25.178.86:8083/mcp
    timeout_seconds: 20
  cn_financial:
    transport: sse                    # SSE
    endpoint: ${CN_FINANCIAL_MCP_ENDPOINT}  # http://118.25.178.86:8000/sse
    timeout_seconds: 20
```

> 客户端解包注意：两个传输的 `async with` 都返回 **2 元组** `(read, write)`，不是 3 元组。代码里不得假设统一接口。

分析能力暂不绑定 Node.js。第一阶段优先以 Python Domain/Analysis Engine 形式实现，跑通完整流程后再评估是否保留现有 Node Skill。`stock-wrapper` 不再属于新架构的运行时组件。

云端部署可规避本机的系统代理与 TLS 指纹问题，但云端 IP 段仍可能被数据源风控——**以实测可达性为准，不假设全量可用**（实测结论见 §7.0）。

---

## 3. 总体业务流程

```text
用户问题
  ↓
Root Graph（runtimes/langgraph/graphs/）
  ↓
load_memory ──── Mem0: get_profile + search（首部读记忆）
  ↓
问题理解与上下文检查（ContextBuilder 组装 7 块上下文）
  ↓
数据需求规划
  ↓
Market Data Acquisition Graph（市场数据获取子图，有界 ReAct）
  ├── Market Data Gateway → akshare-one-mcp（Streamable HTTP）
  ├── Market Data Gateway → cn-financial-mcp（SSE）
  └── Java Data Tool → 用户持仓和账户数据
  ↓
Observation Normalizer（观测结果标准化，含服务端吞错识别）
  ↓
AnalysisInput 组装
  ↓
Analysis Capability（Python Analysis Engine，第一阶段）
  ↓
AnalysisResult 校验
  ↓
Summary Model（总结模型）
  ↓
persist_memory ──── Mem0: add（尾部写记忆）
  ↓
用户确认或最终回答
```

---

## 4. 开发阶段

> 当前优先级：**先实现 LangGraph + Mem0 主版本**。Letta 对比版（Phase 3）在主版本稳定后启动，不在本 Prompt 范围。

### Phase 0：系统骨架（LangGraph + Mem0 + MCP）

- `pyproject.toml` + FastAPI 入口 + `runtimes/shared/` 契约骨架；
- 配置管理（含两个 MCP 的传输类型区分配置）；
- `ToolRegistry` + 两个 MCP 接入（`integrations/mcp/`）；
- LangGraph Root Graph 空骨架（`runtimes/langgraph/graphs/`）；
- Mem0 接入 + `memory/base.py` 抽象（`memory/mem0/`）；
- **MCP 可用性验证**：跑 §7.0 验证矩阵，校准路由表，归档为交付物；
- RootState、Observation、预算契约；
- Checkpointer、`interrupt()`/`Command(resume=...)`、SSE 事件流；
- 一个只读 Mock Tool、最小测试集。

验收：能通过 API 调一次 LangGraph runtime 返回结构化结果；MCP 可用性验证表归档；Mock 数据不写死到领域计算层。

### Phase 1：LangGraph 版核心（含 Mem0 首尾读写）

- `ContextBuilder` 实现（`runtimes/langgraph/context/`，7 块上下文组装，见 §11）；
- Query Graph：问题理解、标的识别、数据需求规划、缺失中断；
- 有界 ReAct agent 循环（预算见 §8）；
- **Mem0 首尾读写打通**：load 节点 `memory.search` + `get_profile`，persist 节点 `memory.add`；
- Market Data Acquisition Graph：统一能力路由、Observation 标准化、数据质量检查；
- Java Data Tool Adapter。

验收：综合分析场景端到端跑通，事件流可追踪，Mem0 失败时降级为无记忆继续跑（见 §10.4）。

### Phase 2：分析能力与确定性计算

- 定义纯分析接口 `analyze(AnalysisInput) -> AnalysisResult`，只消费已标准化输入；
- 第一阶段用 Python 实现：分析指标、风险计算、规则结论放入 `domain/` + Analysis Engine；
- `AnalysisCapabilityAdapter` 预留未来接入 Python 子进程/Node Skill/独立服务的边界，但当前不要求 HTTP 服务；
- `domain/` 补全：backtest 回测引擎、risk 风险指标、market 技术指标，封装为 Tool；
- 切断旧数据耦合：若复用 Node Skill 代码，`src/data/*` 不得引用 `src/analysis/*` 或 HTTP 请求工具。

验收：断网状态下喂入固定 AnalysisInput 仍能产出结构完整的 AnalysisResult；回测结果可复现（固定输入→固定输出）。

### Phase 3：Letta 对比版（不在本 Prompt 范围）

主版本稳定后启动，详见架构文档 §11 Phase 3。

### Phase 4：持仓、策略、回测扩展

Java 持仓服务接入、组合分析、策略设计、回测引擎、知识库。本 Prompt 只预留边界，不提前实现真实交易。

---

## 5. Python 代码目录

统一使用以下目录（对齐架构文档 v3.1 §7），不得再创建第二套入口：

```text
stockwise-analysis/
├── pyproject.toml
├── README.md
├── tests/
└── src/stockwise_analysis/
    ├── main.py
    ├── config.py
    ├── api/                           HTTP/SSE 入口
    │   ├── routes.py
    │   ├── schemas.py
    │   └── sse.py
    ├── runtimes/                      ★ 编排引擎层（本 Prompt 只实现 langgraph）
    │   ├── langgraph/                 主版本
    │   │   ├── graphs/                StateGraph、子图、条件边
    │   │   │   └── subgraphs/
    │   │   ├── agents/                有界 ReAct agent
    │   │   ├── nodes/                 CODE/LLM/TOOL 节点
    │   │   └── context/               ★ ContextBuilder（7 块上下文组装）
    │   ├── letta/                     对比版本（Phase 3，本 Prompt 不实现）
    │   └── shared/                    ★ 两版共享契约（输入输出 Schema、事件类型）
    ├── memory/                        ★ 记忆层（仅 LangGraph 版使用）
    │   ├── base.py                    统一抽象：search / add / get_profile
    │   └── mem0/                      Mem0 实现
    ├── tools/                         自研工具（独立包，Domain 封装）
    │   ├── registry.py                ToolRegistry：按名取工具
    │   ├── runtime.py
    │   ├── models.py
    │   ├── market_data_gateway.py     8 个统一能力暴露给 Agent
    │   ├── java_data_adapter.py
    │   └── mock_tools.py
    ├── integrations/
    │   ├── mcp/                       MCP 服务接入（两种传输分别适配）
    │   │   ├── client.py              连接管理（SSE + Streamable HTTP）
    │   │   ├── adapter.py             MCP→Tool 转换
    │   │   ├── registry.py            允许的 MCP 清单
    │   │   └── routing_policy.py      source 路由/超时/重试
    │   ├── market_data/
    │   └── research_data/
    ├── contracts/
    │   ├── workflow.py                WorkflowPlan、TaskSpec
    │   ├── observation.py             Observation
    │   ├── data_requirements.py       DataRequirement
    │   ├── analysis.py                AnalysisInput、AnalysisResult
    │   └── events.py
    ├── observations/                  Observation 标准化
    │   ├── normalizer.py              ★ 含服务端吞错识别（§7.3 约束 5）
    │   ├── quality.py
    │   └── provenance.py
    └── domain/                        确定性计算（零框架依赖，两版共享）
        ├── indicators.py
        ├── risk.py
        ├── calculations.py
        └── trading_calendar.py        交易日历本地计算
```

目录职责界定：

- `integrations/mcp/` 负责底层连接与原始工具适配，处理 SSE 和 Streamable HTTP 两种传输；
- `tools/market_data_gateway.py` 只把 §7.1 的 8 个统一能力暴露给 Agent，编排"统一能力 → 哪个 MCP/哪个 source"，不碰连接细节；单向调用：`gateway → integrations/mcp/`；
- `memory/` 只服务 LangGraph 版（Letta 版用自带记忆）；`memory/base.py` 定义抽象，`memory/mem0/` 是实现；
- `runtimes/shared/` 放两个 runtime 都要遵守的契约（即使现在只实现 langgraph，也要先把 shared 抽象出来，为 Phase 3 留位）；
- `domain/` 不得 import LangGraph/LangChain/Letta/Mem0，纯确定性逻辑。

---

## 6. LangGraph 流程

### 6.1 Root Graph

```text
receive_request
  ↓
load_memory ──── Mem0 首部读（get_profile + search）
  ↓
understand_request（ContextBuilder 组装上下文）
  ↓
check_missing_context
  ├── 缺少条件 → interrupt_for_clarification
  │                 ↓
  │             Command(resume=...)
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
invoke_analysis_capability
          ↓
validate_analysis_result
          ↓
compose_final_response
          ↓
persist_memory ──── Mem0 尾部写（add）
          ↓
user_confirmation（按需）
          ↓
finish
```

### 6.2 Market Data Acquisition Graph

```text
build_query_plan
  ↓
select_next_data_action（有界 ReAct，仅 comprehensive 完整启用）
  ↓
execute_market_tool（经 MarketDataGateway，按路由表选 source）
  ↓
normalize_observation（含服务端吞错识别）
  ↓
evaluate_data_sufficiency
  ├── 数据完整 → end
  ├── 缺少数据 → select_next_data_action
  ├── 主源失败 → invoke_fallback_source（切 xueqiu/sina）
  ├── 数据冲突 → resolve_data_conflict
  └── 关键数据不可用 → LIMITED 或 interrupt
```

外层 Graph 必须控制 Tool 执行、Observation 追加、预算扣减、失败处理和结束条件。Agent 只输出下一步结构化动作。

---

## 7. MCP Gateway 设计

### 7.0 实测可用性结论（2026-08-06 校准）

push2 系域名的 eastmoney 源在云端**仍被风控**（`RemoteDisconnected`），但 **akshare-one 内部的异构 source（xueqiu/sina）可用**，构成真正的异构备份。完整验证矩阵：

| 能力 | cn-financial（默认源） | akshare-one（eastmoney） | akshare-one（xueqiu/sina） |
|---|---|---|---|
| 实时行情 | ✅ 18.6s（慢，内部已降级） | ❌ 风控 | ✅ **xueqiu 0.6s** |
| 历史 K 线 | ✅ 0.8s（内部已降级） | ❌ 风控 | ✅ **sina 0.6s** |
| 三大报表 | ✅ 5-6s（中文 key，亿元） | ✅ 0.7-1.2s（英文 key，元，更快） | — |
| 北向资金 | ✅ 0.9s | — | — |
| 行业板块 | ✅ 5.6s | — | — |
| 个股资金流 | ❌（服务端吞错，见 7.3 约束 5） | — | — |
| 市场总览 | ❌（服务端吞错，见 7.3 约束 5） | — | — |
| 新闻 | ✅ 0.1s | ✅ 0.1s | — |

**核心结论**：v2.x 关于"同源需接第三方"的判断**已被实测修正**——akshare-one 的 `source=xueqiu`（实时）和 `source=sina`（K线）就是可用异构备份，无需外接第三方。

### 7.1 统一能力名称

Agent 只看到统一能力，不直接看到两个 MCP 的原始工具名：

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

> 交易日历**不作 MCP 能力**。两个 MCP 均无真正交易日历工具。由 `domain/trading_calendar.py` 用 `exchange_calendars` 本地确定性计算，必须经过 A 股调休、补班和特殊交易日测试。

### 7.2 路由策略（实测校准版）

| 统一能力 | 首选 | 备选 | 实测备注 |
|---|---|---|---|
| 标的搜索 | `cn-financial` search_stock | — | 低风险 |
| 实时行情 | `akshare-one` **source=xueqiu** | `cn-financial` get_realtime_quote（慢 18s） | eastmoney 系被风控；xueqiu 0.6s 可用 |
| 原始历史 K 线 | `cn-financial` get_historical_price（0.8s） | `akshare-one` **source=sina**（0.6s） | cn-financial 内部已降级；akshare-one 必须传 sina |
| 财务报表 | `cn-financial`（中文 key，亿元） | `akshare-one`（英文 key，元，更快） | 两者均走 datacenter，稳定；按消费方字段需求选 |
| 估值、行业 | `cn-financial` | — | datacenter 系，稳定 |
| 个股资金流 | `cn-financial` get_money_flow | — | ⚠ 实测服务端吞错（见 7.3 约束 5） |
| 市场总览 | `cn-financial` get_market_overview | — | ⚠ 实测服务端吞错（见 7.3 约束 5） |
| 新闻和公告 | `cn-financial` get_stock_news | `akshare-one` get_news_data | 两者均可用，cn-financial 字段更全 |

### 7.3 强制约束

1. **两个 MCP 连续失败时不得调用分析能力补查**。runtime 必须返回结构化失败或 `LIMITED`。`stock-wrapper` 和旧 `/api/v1/*` 不作备份源（已退役）。**异构备份通过 akshare-one 的 `source` 参数实现**（xueqiu/sina，见 §7.0），无需外接第三方。
2. **两个 MCP 不能同时作为同一字段的并行默认源**。仅在数据校验或冲突分析场景下才主动调第二源。
3. **`akshare-one-mcp` 的历史 K 线**：`get_hist_data` 的 `indicators_list` 参数（SMA/MACD/RSI/BOLL 等）**默认 null，不传即得纯 OHLCV**；若误传则返回带预计算指标的数据，此时预计算指标最多作校验，不作默认结论（与 §10.5 计算责任一致）。
4. **两个 MCP 的参数 schema 不同，MarketDataGateway 必须分别适配**：
   - akshare-one 用 `interval`（day/week/month）+ `interval_multiplier` + `source`，**不是** `period`；
   - cn-financial 用 `period`（daily/weekly/monthly）+ `start_date`/`end_date`；
   - 统一能力层做参数翻译，不让 Agent 感知差异。
5. **cn-financial 的部分工具会把数据源失败包成正常响应**（`{"error": true, "message": "..."}`），MCP 协议层 `isError=false`。**`observations/normalizer.py` 必须解析响应体里的 `error` 字段**，识别为失败并触发降级，不能只依赖 MCP 协议的 isError 标志。已确认 `get_money_flow`、`get_market_overview` 存在此问题。

每次调用必须记录：MCP 名称、统一工具名、原始工具名、请求参数（含 source）、请求时间、数据时间、响应耗时、是否使用备用源、是否发生字段冲突、原始响应引用。

### 7.4 Java 数据 Tool

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

ReAct 只用于市场数据获取子图，不进入分析能力内部。非所有分析类型都启动 ReAct，按以下执行矩阵选择路径：

- `market_snapshot`：确定性快路径，不启动 Agent/ReAct；
- `technical`、`fundamental`、`valuation`：优先固定数据计划，遇到缺失字段、分页或主源失败时才允许有限自适应；
- `portfolio_impact`：在 Java 用户数据和市场数据依赖不完整时允许有限 ReAct；
- `comprehensive`：允许完整但有界的 ReAct。

每轮只生成一个动作：

```json
{
  "action": "get_historical_prices",
  "arguments": { "symbol": "600000", "period": "daily", "lookback_days": 120 },
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

- 单轮模型决策：10 秒；单个 MCP Tool：20 秒（含云端 RTT）；单个 Java Tool：10 秒；单次分析能力调用：60 秒；
- 主源失败后最多切换 1 次异构 source（xueqiu/sina）；连续失败则标记数据维度不可用，返回 `PARTIAL` 或 `LIMITED`；
- 财报类分页拉取若超过单 Tool 超时，应支持分页续传而非整体失败；分页请求必须携带 `page_token`、`page_size`、`source_request_id`，记录已完成页，恢复时不得重复写入。

只有 `comprehensive` 进入完整 ReAct；其他类型按有限自适应规则执行。超出预算必须停止并输出 `LIMITED`。

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

MCP、Java Tool 和分析能力的外部结果都必须经过统一标准化。**未经标准化的原始 JSON 不得直接进入最终 Prompt，也不得直接交给分析能力**。标准化层必须识别服务端吞错（§7.3 约束 5）。

---

## 10. 分析能力契约（部署形态后置）

### 10.1 调用方式

第一阶段默认在 Python Analysis Engine 中直接调用：

```python
result = analysis_capability.analyze(analysis_input)
```

LangGraph 通过 `AnalysisCapabilityAdapter` 调用，不在节点中硬编码具体实现。后续若评估决定部署为独立 Skill 服务，再由 Adapter 封装 HTTP/进程细节；当前不要求实现 Node HTTP 服务。

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

所有数据块至少包含 `as_of`、`source`、`retrieved_at`、`quality_status`；禁止用无法追溯来源的裸 `dict` 作为核心契约。核心类型最低字段：

| 类型 | 必填字段 |
|---|---|
| `InstrumentRef` | `symbol`、`name`、`market`、`exchange`、`instrument_type` |
| `DataQuality` | `completeness`、`freshness`、`quality_status`、`known_unavailable` |
| `ProvenanceRecord` | `source`、`tool`、`request_id`、`as_of`、`retrieved_at`、`fallback_used` |
| 分页信息 | `page_token`、`page_size`、`source_request_id`、`completed_pages` |

支持的 `analysis_type`：`market_snapshot` / `technical` / `fundamental` / `valuation` / `portfolio_impact` / `comprehensive`。分析类型只决定使用哪些已提供的数据，不代表自行查询数据。

> `overseas_context`（外围面，纳斯达克/恒生科技等）两个 MCP 均不覆盖，来源待定；落实前 `comprehensive` 的外围面标记 `PARTIAL`，不得编造。

### 10.3 分析能力禁止事项

禁止访问 MCP / Java API / 数据库 / 行情接口；禁止按股票代码自行补数；禁止内部启动 ReAct；禁止决定下一步工具。

### 10.4 AnalysisResult

```python
class AnalysisResult(BaseModel):
    schema_version: str
    analysis_id: str
    status: str            # SUCCESS / PARTIAL / LIMITED / FAILED
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

### 10.5 计算责任

MCP 返回原始数据，分析能力/Python Domain 层负责计算：

```text
OHLCV → MA/EMA/MACD/RSI/ATR → 波动率/最大回撤/支撑阻力 → 技术信号/风险标记/分析结论
```

必须记录指标参数、复权方式、时间范围、算法版本，并防止未来函数。MCP 预计算指标最多作校验，不作默认结论。

---

## 11. Mem0 记忆层设计（LangGraph 版专属）

### 11.1 读写边界（仅首尾）

```text
对话开始（Root Graph 的 load_memory 节点）:
  profile = memory.get_profile(user_id)         # 结构化画像
  recalled = memory.search(user_input, user_id) # 语义召回
  → 注入 ContextBuilder 的第 ②⑤ 块

对话进行（agent ReAct 循环）:
  不碰 memory（保证流程确定性）

对话结束（Root Graph 的 persist_memory 节点）:
  memory.add(本轮对话摘要 + 抽取要点, user_id)  # 沉淀
```

### 11.2 记忆内容分层

| 层 | 存什么 | 形态 | 来源 |
|---|---|---|---|
| 结构化画像 | 风险偏好、偏好板块、禁忌标的 | PG 表字段 | LLM 定期归纳 |
| 语义记忆 | 历史研究结论、用户观点、知识片段 | Mem0（pgvector） | persist 节点 Mem0.add |
| 热层对话 | 最近 N 轮原文 | Redis | 实时写入 |

### 11.3 工程约束（Phase 0 接入时必须明确）

| 约束项 | 要求 |
|---|---|
| Mem0 内部 LLM | 显式配置为 DeepSeek（与主链路同模型），不得用 Mem0 默认 OpenAI；通过 `llm` 参数注入 |
| Embedding | 显式配置为 Qwen3-Embedding，不得走默认 |
| 成本上限 | Mem0.add 单次内部 LLM 轮数需有上限，配置 token 预算参数 |
| **失败降级** | Mem0 不可用时降级为"无记忆继续跑"——`search` 失败返回空、`add` 失败仅记日志不阻塞主流程。**记忆是增强项，不是关键路径，挂了不能拖垮分析流程** |
| 延迟计入 | load/persist 节点的 Mem0 耗时计入 §8 总请求预算 |
| 可观测 | 每次调用记录：操作类型、user_id、耗时、是否命中降级、内部 LLM token 消耗 |

---

## 12. ContextBuilder 设计（LangGraph 版专属）

每轮调用大模型前，由 `runtimes/langgraph/context/` 组装完整上下文：

```text
① System Prompt     固定（写死）
② 用户画像          来自 PG 结构化表（确定性）
③ 工具清单          来自 ToolRegistry（确定性）
④ 近期对话历史      来自 PG/Redis（确定性，带截断）
⑤ 召回的相关记忆    来自 Mem0（语义，带容差）
⑥ 本轮已取数据      工具调用结果（本轮）
⑦ 用户当前输入      HTTP 请求体
```

7 块中 6 块确定性，仅 ⑤ 是语义召回（不准则只影响"是否贴合历史"，不影响计算正确性）。每块都能单元测试——这是 LangGraph 版"黑箱可控"的体现。

---

## 13. 错误、降级和中断

### MCP 失败

1. 记录失败原因；2. 判断是否允许切异构 source（xueqiu/sina）；3. 备用成功则继续并记录来源变化；4. 备用失败则标记 Observation 无效；5. 不允许编造缺失数据。

### 数据不足

- 缺少标的或时间范围：`interrupt()` 请求补充；
- 非关键数据缺失：继续并标记 `PARTIAL`；
- 关键数据缺失：输出 `LIMITED`；
- 外围面缺失：标记 `PARTIAL`，limitations 说明，不得编造；
- 数据源冲突：保留两个 Observation，进冲突处理；
- 无法判断冲突：停止生成确定性结论。

### 逃生阀（异构 source 仍失效时）

akshare-one 的 xueqiu/sina 若也失效：1. 将该数据域标记"**已知不可用**"，写入 `data_quality.known_unavailable`；2. limitations 如实说明"行情数据当前因数据源问题不可获取，以下分析基于截至 X 时的数据"；3. 不得调用分析能力/stock-wrapper/旧 `/api/v1/*` 补查，不得编造。

### Mem0 失败

按 §11.3 降级：`search` 失败返回空、`add` 失败仅记日志，主流程继续。记忆是增强项不是关键路径。

### 分析能力失败

只允许 `AnalysisCapabilityAdapter` 层有限重试或返回结构化失败，不允许分析能力自行查询数据。Python 本地实现则记录异常返回 `FAILED`。

---

## 14. API 与事件流

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
run_started / node_started / model_decision / tool_started / tool_finished
observation_created / fallback_triggered / memory_read / memory_written
analysis_started / analysis_finished / interrupt_created / run_finished / run_failed
```

事件必须记录 `run_id`、`thread_id`、节点名、工具名、耗时、状态和错误信息，支持前端追踪完整执行过程。

---

## 15. 必须完成的开发内容

按以下顺序实现：

1. Python 基础 Runtime、配置（含两 MCP 传输区分）、启动入口；
2. `runtimes/shared/` 契约骨架（即使现在只实现 langgraph）；
3. RootState、Observation、WorkflowPlan、DataRequirement、AnalysisInput、AnalysisResult；
4. Checkpointer、interrupt/resume、事件流；
5. ToolRegistry、Tool Runtime、Mock Tool；
6. MCP Client（SSE + Streamable HTTP 两种）、MCP Adapter、MarketDataGateway；
7. 接入两个 MCP，**跑 §7.0 可用性验证，校准路由表并归档**；
8. Observation 标准化（含服务端吞错识别）、数据质量检查；
9. Mem0 接入 + `memory/base.py` 抽象，load/persist 节点；
10. ContextBuilder（7 块上下文）；
11. Root Graph、Query Graph、Market Data Graph、有界 ReAct；
12. Java Data Tool Adapter；
13. Python Analysis Engine：`analyze(AnalysisInput) -> AnalysisResult`，`domain/` 指标/风险计算；
14. `AnalysisCapabilityAdapter`（默认 Python 实现，预留服务化边界）；
15. 分析输出校验、最终总结节点；
16. 异常、超时、降级、数据冲突、Mem0 失败降级、恢复测试；
17. 更新 README 和运行配置。

> 第 7 步的可用性验证：逐个调关键工具，记录可达性、耗时、是否触发 source 切换、是否命中服务端吞错。验证结果校准 §7.2 路由表，并作为 §17 交付物归档。未通过验证的能力不得作为默认数据源。

---

## 16. 明确禁止的实现方式

- 不允许分析能力内部查询任何外部数据；
- 不允许 Agent 直接管理两个 MCP 连接；
- 不允许两个 MCP 的重复工具同时暴露给模型；
- 不允许未经标准化的 MCP 原始响应直接交给分析能力（含服务端吞错未识别的情况）；
- 不允许 ReAct 循环中读写 Mem0（记忆仅首尾）；
- 不允许 Mem0 失败时拖垮主流程（必须降级为无记忆继续跑）；
- 不允许使用无限循环 ReAct；
- 不允许让大模型替代确定性指标和风险计算；
- 不允许在本阶段接入真实下单、撤单或交易执行；
- 不允许因为数据缺失编造行情、财务指标或结论；
- 不允许修改旧 Java Agent 来绕过新 Python 流程；
- 不允许创建第二套 Python 应用目录或入口；
- 不允许假设两个 MCP 用同一种传输协议或同一套参数 schema。

---

## 17. 验收场景

### 场景一：综合市场分析

```text
用户问题 → 问题理解 → 数据需求规划 → MCP 查询（含 source 路由）
→ Observation 标准化 → 分析能力计算 → AnalysisResult 校验 → 大模型最终回答
```

### 场景二：涉及当前持仓

同时调用 `Java Portfolio Tool + Market Data Gateway + Analysis Capability`，输出标的对用户持仓的影响。

### 场景三：主源失败 + 异构 source 降级

eastmoney 源被风控时，自动切 akshare-one 的 `source=xueqiu/sina`，事件流和结果记录来源变化。

### 场景四：数据不足

触发 `interrupt()` 请求补充，或返回 `LIMITED`，不得生成虚假确定性结论。

### 场景五：分析能力不可用

返回结构化错误、运行轨迹和失败原因，不得退化为让分析能力自行查询数据。

### 场景六：Mem0 失败降级

Mem0 不可用时，主流程以"无记忆"模式继续完成分析，不抛致命错误，事件流记录 `memory_read`/`memory_written` 的降级。

### 场景七：可恢复运行

同一 `thread_id` + Checkpointer 从用户中断点继续，不重复执行已完成步骤。

---

## 18. 最终交付报告

完成后必须输出：

- 新增和修改文件清单；
- 运行方式和环境变量清单（含两 MCP endpoint、Mem0 配置、DeepSeek、Qwen3-Embedding）；
- LangGraph 节点及状态说明；
- **MCP 统一工具和路由表**（实测校准版，含 source 路由、参数翻译、吞错识别）；
- **数据源可用性验证报告**（能力 × MCP × source × 可达性 × 耗时 × 是否触发降级），以及据此校准后的最终路由表；
- **Mem0 记忆层说明**：base 抽象、首尾读写实现、降级测试结果、内部 LLM/Embedding 配置；
- **ContextBuilder 说明**：7 块上下文组装、单元测试覆盖；
- **分析能力实现说明**：Python Analysis Engine 接口、数据依赖、断网 fixture 测试结果；
- `AnalysisInput` / `AnalysisResult` 请求与响应示例；
- 事件流示例；
- 测试命令和测试结果；
- 未实现内容（Letta 版等）；
- 已知风险（含 push2 风控、服务端吞错、外围面缺失、Mem0 黑箱质量等）；
- 后续开发建议。

最终执行原则：

> 先建立可恢复、可追踪、可测试的 LangGraph + Mem0 流程，再接入 MCP 和分析能力；MCP 负责取数（含 source 异构降级），分析能力负责分析，Mem0 首尾负责记忆，LangGraph 负责统一编排。
