# StockWise 金融随身管家
# 需求更新版（LangGraph + Mem0 当前实施基线）

> 版本：v1.0
> 状态：当前需求基线
> 适用项目：`stockwise-analysis`
> 当前运行时：LangGraph
> 当前记忆层：Mem0
> 当前数据接入：MCP + Java Data API
> 当前分析能力：Python Analysis Capability
>
> 本文档是新的需求更新版，不修改主开发文档
> `23-全新股票分析系统-统一开发实施Prompt.md`。
> 后续开发以本文档作为“金融随身管家形态”的补充需求说明；如果本文档与主 Prompt 的固定股票流程发生冲突，以本文档中关于“对话优先、动态工具选择、非固定路由”的要求为新的调整方向。
>
> 当前阶段暂不引入 Letta、Hermes、Phoenix、Langfuse、DeepEval、Promptfoo、Garak 或其他新增 Agent 平台。本文档只要求把现有 LangGraph + Mem0 + MCP + Java API 体系做完整。

---

## 1. 需求背景

StockWise 不再被定义为只能围绕单只股票代码运行的固定分析系统，而是定义为：

> 面向金融领域的通用对话式智能管家（Financial Personal Assistant）。

用户可以像使用通用对话助手一样与系统交流，但系统的专业范围重点集中在：

- 股票和证券市场；
- 指数、板块和行业；
- 宏观经济和跨市场影响；
- 新闻、公告和事件分析；
- 用户持仓和风险分析；
- 投资知识解释；
- 基于真实数据的金融研究辅助。

系统不要求每个问题都包含股票代码，也不要求每个问题都先归类为某一个固定业务流程。

例如以下问题都属于合法输入：

```text
美国非农数据对中国 A 股有什么影响？
最近新能源板块为什么波动比较大？
帮我比较两个行业的估值和资金流向。
刚才提到的那只股票最近风险怎么样？
我的持仓整体暴露在哪些风险上？
什么是市盈率？
最近市场为什么持续下跌？
如果美联储继续加息，A 股可能受到哪些影响？
```

系统需要根据问题内容动态判断：

- 是否可以直接回答；
- 是否需要读取会话记忆；
- 是否需要调用 MCP 数据工具；
- 是否需要调用 Java 用户数据工具；
- 是否需要加载某个分析 Skill；
- 是否需要多个工具连续调用；
- 是否需要向用户补充提问；
- 是否需要用户确认高风险操作。

---

## 2. 本次需求更新的核心结论

### 2.1 从固定工作流改为对话式 Agent

旧模式：

```text
用户问题
  → QueryIntent
  → 固定 route
  → 固定分析流程
  → 返回结果
```

新模式：

```text
用户问题
  → 金融管家 Agent
  → 自主判断下一步行动
  → 直接回答 / 调用工具 / 加载 Skill / 继续分析 / 询问用户
  → 返回结果
```

LangGraph 仍然负责状态、循环、工具执行、预算、中断和恢复，但不再被实现成一组必须命中的固定业务路线。

### 2.2 Route 不再作为用户问题的强制分类

`route_type`、`analysis_type` 等字段可以在迁移期间保留，但只能用于：

- 兼容已有代码；
- 记录本次运行的执行信息；
- 选择已有分析能力的执行配置；
- 生成监控和审计信息。

它们不能再承担以下职责：

- 要求所有问题必须命中某个固定类型；
- 要求用户必须提供股票代码；
- 决定唯一的完整执行流程；
- 代替 Agent 进行下一步行动判断；
- 将宏观、行业、市场和跨市场问题强行压缩为股票分析。

### 2.3 QueryIntent 不再等于执行路线

`QueryIntent（问题意图）`只负责表达用户想完成什么事情，例如：

```text
用户想了解美国非农数据与中国 A 股之间的影响关系。
```

它不直接决定：

- 调用哪个 MCP 工具；
- 调用多少次工具；
- 是否执行 ReAct；
- 是否调用 Java API；
- 是否加载哪个具体 Skill。

这些判断属于 Agent 的执行决策和工具选择阶段。

### 2.4 当前不引入新的 Agent 平台

当前只完成已有系统：

```text
LangGraph       Agent 状态和执行循环
Mem0            会话外长期记忆
MCP             外部金融数据工具
Java Data API   用户、账户和持仓数据
Python Analysis 本地确定性分析能力
FastAPI/SSE     对外服务接口和流式输出
```

Letta 只保留未来替换运行时的边界，不在当前阶段实现。

---

## 3. 产品定位与用户体验

### 3.1 产品定位

StockWise 是一个金融领域的对话式 Agent，而不是一个只能执行固定菜单的查询接口。

用户不需要了解：

- 应该使用哪个 route；
- 应该调用哪个 MCP；
- 应该传入哪个接口参数；
- 应该选择哪个分析类型；
- 是否需要先提供股票代码。

用户只需要自然语言描述目标。

### 3.2 对话连续性

系统必须支持上下文引用：

```text
用户：帮我看看某行业最近的表现。
系统：返回行业分析。
用户：那它和另一个行业相比怎么样？
系统：解析“它”和“另一个行业”的上下文关系。
用户：如果我持有其中相关股票，风险大吗？
系统：结合前文实体和用户持仓继续分析。
```

系统需要保留：

- 当前会话消息；
- 当前 Agent 执行状态；
- 已解析实体；
- 已获取的 Observation；
- 上一轮工具结果；
- 用户已经确认的条件；
- 必要的长期用户偏好。

### 3.3 回答自由性与金融边界

系统可以自由理解开放式金融问题，但不能：

- 编造实时行情；
- 把未查询到的数据当成真实数据；
- 将分析意见伪装成确定性收益承诺；
- 未经确认执行交易或修改用户敏感资料；
- 绕过工具白名单直接访问 MCP、数据库或 Java 服务；
- 因为用户没有提供股票代码就停止所有分析。

---

## 4. 当前系统范围

### 4.1 当前必须支持

| 能力 | 是否必须 | 说明 |
|---|---:|---|
| 通用金融问答 | 是 | 可直接由模型回答的基础问题 |
| 股票和指数数据查询 | 是 | 通过 MCP 获取最新或历史数据 |
| 市场整体分析 | 是 | 不要求股票代码 |
| 板块和行业分析 | 是 | 不要求单只股票代码 |
| 宏观经济分析 | 是 | 支持宏观指标和市场影响解释 |
| 跨市场影响分析 | 是 | 例如海外宏观事件对中国 A 股的影响 |
| 新闻和事件分析 | 是 | 以工具获取的外部内容为依据 |
| 用户持仓分析 | 是 | 通过 Java Data API 获取持仓数据 |
| 多轮上下文对话 | 是 | 解析“刚才那只”“这两个行业”等引用 |
| 多工具连续调用 | 是 | 由 Agent 根据执行结果决定是否继续 |
| 结构化数据分析 | 是 | 交给 Python Analysis Capability |
| 流式输出 | 是 | 通过现有 FastAPI/SSE 服务返回事件 |

### 4.2 当前不支持

当前阶段不实现：

- 真实下单、撤单和交易执行；
- 未经确认修改用户风险偏好；
- 未经确认生成并执行交易计划；
- 无限循环 ReAct；
- Agent 直接访问数据库；
- Agent 直接调用 MCP 原始工具；
- Skill 内部自行查询外部市场数据；
- 强制引入 Letta 或其他 Agent 平台；
- 强制引入新的可观测性或评测平台；
- 把普通分析结果都写入长期记忆。

---

## 5. 总体技术架构

```text
┌─────────────────────────────────────────┐
│ StockWise Assistant Service              │
│ FastAPI + SSE                            │
│                                         │
│ LangGraph Agent Runtime                  │
│ Conversation State                       │
│ Agent Decision Loop                      │
│ Context Builder                          │
│ Interrupt / Resume                       │
└──────────────────┬──────────────────────┘
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
   Mem0 Memory   Tool Gateway  Skill Adapter
   记忆层        工具网关       分析能力适配器
       │           │           │
       │     ┌─────┴─────┐     │
       │     ▼           ▼     │
       │   MCP         Java API│
       │   金融数据     用户数据│
       │                   ▼   │
       └────────────── Python Analysis
                       Capability
                       确定性分析
```

### 5.1 LangGraph 的职责

LangGraph 是当前 Agent Runtime（智能体运行时），负责：

- 管理对话和运行状态；
- 执行 Agent 决策循环；
- 控制工具调用；
- 接收工具返回的 Observation；
- 判断是否继续、回答或询问用户；
- 管理预算和最大循环次数；
- 管理 `interrupt()` 和 `Command(resume=...)`；
- 通过 Checkpointer 保存可恢复状态；
- 向 SSE 输出过程事件。

LangGraph 不应被实现为“每个问题必须命中的固定 Route 列表”。

### 5.2 Mem0 的职责

Mem0 负责：

- 用户偏好；
- 用户长期投资目标；
- 用户风险偏好；
- 用户明确要求记住的信息；
- 对后续对话有帮助的稳定事实。

Mem0 不负责：

- 当前 Graph 状态保存；
- MCP 原始响应缓存；
- 工具调用过程控制；
- 代替 Checkpointer；
- 代替分析历史记录；
- 自动将每一次普通回答写入长期记忆。

### 5.3 Tool Gateway 的职责

Agent 不能直接看到和调用两个 MCP 的原始工具集合，而应该通过统一的 Tool Gateway（工具网关）调用能力。

统一能力示例：

```text
market.resolve_instrument
market.get_realtime_quote
market.get_historical_prices
market.get_financial_statements
market.get_valuation
market.get_industry_context
market.get_money_flow
market.get_news
macro.get_indicator
macro.get_release_history
portfolio.get_current_positions
portfolio.get_account_snapshot
portfolio.get_transaction_history
user.get_risk_profile
```

Tool Gateway 负责：

- 参数 Schema 校验；
- MCP 和 Java API 适配；
- 工具白名单；
- 超时和重试；
- 数据源选择；
- MCP 响应解析；
- `error: true` 业务错误识别；
- Observation 标准化；
- 数据来源和时间记录；
- 失败和降级处理。

### 5.4 Analysis Capability 的职责

Python Analysis Capability 只接收已经标准化的数据：

```text
AnalysisInput → AnalysisResult
```

它可以负责：

- 指标计算；
- 风险计算；
- 技术指标；
- 估值计算；
- 历史事件窗口统计；
- 数据对比；
- 结果结构化总结。

它不能负责：

- 查询 MCP；
- 查询 Java 数据库；
- 发起 HTTP 查询；
- 决定用户意图；
- 决定是否继续调用工具；
- 直接修改记忆；
- 直接执行交易。

---

## 6. Agent 主流程需求

### 6.1 主 Graph

```text
receive_request
  ↓
load_context
  ↓
preprocess_message
  ↓
agent_decide
  ├─ DIRECT_RESPONSE
  ├─ CALL_TOOL
  ├─ LOAD_SKILL
  ├─ ASK_USER
  ├─ REQUEST_CONFIRMATION
  └─ FINISH
  ↓
execute_action
  ↓
normalize_observation
  ↓
agent_decide
  ↓
compose_response
  ↓
persist_run_and_memory
  ↓
finish
```

### 6.2 节点类型

| 节点类型 | 中文 | 使用场景 |
|---|---|---|
| `CODE` | 确定性代码节点 | 状态检查、预算、Schema 校验、结果合并 |
| `DIRECT_LLM` | 单次模型调用 | 普通解释、最终表达、简单问答 |
| `STRUCTURED_LLM` | 结构化模型调用 | 意图理解、动作决策、结果校验 |
| `TOOL_ONLY` | 工具调用节点 | MCP、Java API、内部计算工具 |
| `BOUNDED_REACT_AGENT` | 有界 ReAct Agent | 需要多轮选择工具的复杂研究任务 |
| `SUBGRAPH` | LangGraph 子图 | 可独立运行的专业分析能力 |
| `INTERRUPT` | 中断节点 | 关键歧义、权限缺失、高风险确认 |

### 6.3 简单问题处理

对于可以直接回答的问题，不能强制创建复杂任务计划：

```text
用户问题
  → load_context
  → agent_decide
  → DIRECT_RESPONSE
  → 返回回答
```

### 6.4 数据问题处理

对于需要最新数据的问题：

```text
用户问题
  → agent_decide
  → 选择统一 Tool
  → Tool Gateway
  → MCP / Java API
  → Observation
  → agent_decide
  → 分析或继续查询
```

### 6.5 复杂研究问题处理

对于宏观、跨市场、历史事件或多实体问题，Agent 可以先生成短期任务计划，但任务计划是本次运行的动态产物，不是固定业务 Route。

例如：

```text
用户：美国非农数据对中国 A 股有什么影响？

Agent 动态决定：
1. 查询最近一期美国非农数据
2. 查询美国失业率和薪资数据
3. 查询美元、利率或人民币汇率变化
4. 查询中国 A 股市场表现
5. 必要时查询历史事件窗口
6. 分析宏观影响传导链
7. 生成带数据时间和限制说明的回答
```

这个过程不要求生成一个固定的 `cross_market_route`，而是由 Agent 根据任务需要动态调用能力。

---

## 7. QueryIntent 需求

### 7.1 QueryIntent 的定位

`QueryIntent` 仅用于表达用户问题，不负责执行。

推荐保留并扩展为：

```python
class QueryIntent(BaseModel):
    request_summary: str
    goals: list[IntentGoal] = Field(default_factory=list)
    entities: list[IntentEntity] = Field(default_factory=list)
    time_range: TimeRange | None = None
    requested_dimensions: list[str] = Field(default_factory=list)
    output_preferences: dict[str, Any] = Field(default_factory=dict)
    conversation_references: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float | None = None
    clarification_suggestion: str | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)
```

### 7.2 目标和实体

```python
class IntentGoal(BaseModel):
    goal_id: str
    goal_type: str
    description: str
    entity_refs: list[str] = Field(default_factory=list)
    requested_outputs: list[str] = Field(default_factory=list)


class IntentEntity(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    symbol: str | None = None
    market: str | None = None
    role: str | None = None
    resolution_status: str = "UNRESOLVED"
    attributes: dict[str, Any] = Field(default_factory=dict)
```

支持的实体不应只包含股票：

```text
instrument     股票或证券
index          指数
sector         板块
industry       行业
market         市场
portfolio      用户持仓
macro          宏观指标或宏观事件
news_topic     新闻主题
concept        概念
unknown        暂时无法分类的实体
```

### 7.3 意图理解规则

QueryIntent Agent 必须：

- 支持开放式自然语言；
- 支持多个目标；
- 支持多个实体；
- 支持跨市场关系；
- 支持没有股票代码的问题；
- 支持上下文引用；
- 保留无法解析的原始实体；
- 使用结构化输出；
- 不直接调用 MCP、Java 或数据库；
- 不自行猜测股票代码；
- 不直接决定是否 `interrupt()`；
- 不因为字段为空就强制中断。

`analysis_type` 可以暂时保留，但只能作为旧代码兼容字段或执行配置派生字段。

---

## 8. Agent Action 决策

Agent 的核心输出不是固定 Route，而是下一步动作。

建议使用：

```python
class AgentAction(BaseModel):
    action_type: Literal[
        "DIRECT_RESPONSE",
        "CALL_TOOL",
        "LOAD_SKILL",
        "ASK_USER",
        "REQUEST_CONFIRMATION",
        "FINISH",
    ]
    reason: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    skill_name: str | None = None
    question: str | None = None
    expected_output: str | None = None
```

Agent 决策必须经过代码层校验：

- 工具是否在白名单；
- 参数是否符合 Schema；
- 用户是否有权限；
- 是否超出本次预算；
- 是否属于只读能力；
- 是否需要用户确认；
- 是否已经获得足够的 Observation。

模型可以提出动作，但不能绕过代码层直接执行动作。

---

## 9. Skill 需求

### 9.1 Skill 的定位

当前 Skill 只负责分析、计算和总结，不负责查询数据。

```text
MCP / Java API
  → 获取数据
  → Observation Normalizer
  → AnalysisInput
  → Skill / Python Analysis Capability
  → AnalysisResult
```

### 9.2 Skill 可以做什么

- 根据标准化行情计算指标；
- 根据财务数据完成基本面分析；
- 根据估值数据进行估值解释；
- 根据宏观和市场数据分析影响关系；
- 根据历史事件数据进行窗口统计；
- 根据持仓数据进行风险分析；
- 生成结构化分析结论。

### 9.3 Skill 不可以做什么

- 直接调用 MCP；
- 直接调用 Java API；
- 直接访问数据库；
- 自己发起网络请求；
- 自行补查缺失数据；
- 直接决定用户下一步动作；
- 直接写入 Mem0；
- 直接执行交易；
- 返回没有来源和数据时间的结论。

### 9.4 Skill 调用形式

普通分析优先使用确定性 Python 能力：

```text
AnalysisInput → Python Analysis Capability → AnalysisResult
```

只有在需要自然语言解释、复杂推理或结果总结时，才使用模型节点。

远程 Node Skill 或其他 Skill 服务暂不作为当前阶段依赖。

---

## 10. ReAct 需求

### 10.1 ReAct 的使用边界

ReAct（推理-行动循环）不是所有问题的默认模式。

以下场景不需要 ReAct：

- 基础金融知识解释；
- 已有完整数据的结果总结；
- 单一工具即可完成的查询；
- 确定性指标计算；
- 最终回答生成。

以下场景可以使用有界 ReAct：

- 需要连续调用多个数据工具；
- 第一个工具结果决定下一个工具；
- 数据源不完整，需要判断是否继续检索；
- 跨市场、宏观事件或历史事件研究；
- 多实体比较；
- 需要在多个合法数据能力中动态选择。

### 10.2 ReAct 执行约束

```text
Agent Decide
  → Tool Gateway
  → Observation
  → Agent Decide
```

必须限制：

- 最大 ReAct 轮数；
- 最大工具调用次数；
- 单次工具超时时间；
- 总请求预算；
- 单个子任务预算；
- 失败重试次数；
- 重复工具调用次数。

ReAct Agent 不得：

- 直接调用 MCP 原始客户端；
- 直接访问数据库；
- 修改用户数据；
- 修改长期记忆；
- 无限循环；
- 以工具失败为理由编造数据。

---

## 11. 中断与用户确认

### 11.1 不应触发中断的情况

以下情况不得因为缺少股票代码而中断：

- 市场整体趋势；
- 宏观经济问题；
- 跨市场影响问题；
- 行业和板块分析；
- 指数分析；
- 金融知识解释；
- 可以基于合理默认范围回答的问题；
- 非关键字段缺失但仍可输出部分结果的问题。

### 11.2 可以触发中断的情况

只在继续执行会导致明显错误或风险时中断：

- 比较任务缺少比较对象；
- 股票名称对应多个候选且无法消歧；
- 用户说“刚才那只”但会话中不存在对应实体；
- 用户要求分析个人持仓，但身份或权限不可用；
- 时间范围对结果影响重大且无法合理推断；
- 用户要求执行交易或修改敏感信息；
- 即将产生外部副作用且缺少确认。

### 11.3 普通分析不要求保存确认

普通分析完成后：

- 自动由 Checkpointer 保存运行状态；
- 自动记录必要的 Analysis History；
- 不询问用户“是否保存本次分析”；
- 只在用户明确要求记住或修改敏感画像时写入长期记忆；
- 交易、调仓、修改风险偏好等高风险动作必须确认。

---

## 12. 记忆和状态需求

必须区分以下四类数据：

| 类型 | 作用 | 存储方式 |
|---|---|---|
| Conversation State | 当前对话和 Agent 状态 | LangGraph State |
| Checkpoint | 中断后恢复 | LangGraph Checkpointer |
| Analysis History | 历史分析记录和审计 | 当前项目持久化层 |
| Long-term Memory | 用户长期偏好和稳定事实 | Mem0 |

### 12.1 Mem0 读取

在一次对话开始时，可以读取：

- 用户画像；
- 风险偏好；
- 投资目标；
- 最近相关记忆。

Mem0 读取失败时，主流程仍然可以继续执行，只能减少上下文，不得导致整个请求失败。

### 12.2 Mem0 写入

只保存对未来有价值的信息：

- 用户明确要求记住的内容；
- 稳定的用户偏好；
- 用户确认后的风险偏好；
- 长期投资目标；
- 对后续对话有帮助的稳定事实。

不要自动保存：

- 每次普通行情数据；
- 每次临时分析结论；
- 未经确认的风险偏好推断；
- 敏感账户信息；
- MCP 原始响应全文。

### 12.3 Letta 迁移边界

当前不实现 Letta，但代码必须避免把 Mem0 直接写死在所有业务节点中。

建议通过抽象接口隔离：

```python
class MemoryProvider(Protocol):
    async def recall(self, user_id: str, query: str): ...
    async def save(self, user_id: str, content: str): ...
    async def get_profile(self, user_id: str): ...
```

当前实现：

```text
Mem0MemoryProvider
```

未来如果切换 Letta，只替换 Provider 或 Runtime Adapter，不修改 MCP、Java API、AnalysisInput 和 AnalysisResult 契约。

---

## 13. Observation 和数据质量

所有工具结果必须先转成统一的 Observation，再交给 Agent 或分析能力。

Observation 至少包含：

```text
observation_id
capability
status
data
source
source_tool
requested_at
data_time
quality
provenance
error
limitations
```

### 13.1 MCP 响应解析

不能只依赖 MCP 协议层的 `isError`。

如果 MCP 返回：

```json
{
  "error": true,
  "message": "upstream service failed"
}
```

即使 MCP 协议层连接成功，也必须被标准化为：

```text
Observation.status = FAILED
```

不能把服务端业务错误当作正常数据交给分析层。

### 13.2 数据状态

至少支持：

```text
SUCCESS       数据完整
PARTIAL       数据部分可用
FAILED        工具调用失败
LIMITED       预算或数据源限制导致无法继续
NOT_REQUIRED  当前问题不需要该数据
```

模型必须根据 Observation 的状态生成回答，不得隐藏数据缺失。

---

## 14. 运行预算和降级

预算是一次 Agent 运行的系统资源预算，不是用户投资金额。

预算至少限制：

- 模型调用次数；
- ReAct 最大轮数；
- Tool 调用次数；
- 单个 Tool 超时；
- 总请求时长；
- 子任务时长；
- Analysis Capability 调用次数。

### 14.1 动态预算原则

不再只按一个固定 `analysis_type` 分配全部预算，而是根据当前运行实际需要动态消耗：

```text
总预算
├─ Agent 决策预算
├─ Tool 调用预算
├─ ReAct 循环预算
├─ Analysis Capability 预算
└─ 最终回答预算
```

### 14.2 降级原则

- 工具失败：重试或选择已定义的备用能力；
- 非关键数据缺失：返回 `PARTIAL`，继续分析；
- 关键数据缺失：返回 `LIMITED`，明确说明限制；
- 所有数据源失败：停止继续猜测，返回结构化失败结果；
- Mem0 失败：无记忆继续运行；
- 分析能力失败：返回已获取数据和分析失败说明；
- 超出预算：停止调用并返回当前可用结果。

不允许使用已明确废弃的 `stock-wrapper` 或旧查询接口作为隐式备用数据源。

---

## 15. API 和事件流

当前继续使用 FastAPI + SSE。

### 15.1 请求入口

请求至少包含：

```json
{
  "thread_id": "conversation-thread-id",
  "user_id": "user-id",
  "message": "美国非农数据对中国A股有什么影响？",
  "metadata": {}
}
```

### 15.2 事件类型

建议支持：

```text
run.started
context.loaded
agent.decided
tool.started
tool.completed
tool.failed
observation.created
skill.started
skill.completed
interrupt.required
response.delta
response.completed
run.completed
run.failed
```

### 15.3 恢复执行

发生中断时：

1. 使用 Checkpointer 保存状态；
2. 向前端发送 `interrupt.required`；
3. 返回需要用户补充或确认的内容；
4. 使用相同 `thread_id`；
5. 通过 `Command(resume=...)` 恢复执行；
6. 不重复执行已经完成的工具调用。

---

## 16. 关键验收场景

### 场景一：普通金融知识

```text
用户：什么是市盈率？
```

期望：

- 不调用 MCP；
- 不要求股票代码；
- 不触发 interrupt；
- 直接返回解释。

### 场景二：单只股票数据分析

```text
用户：分析某股票最近一个月的走势。
```

期望：

- 解析股票实体；
- 必要时调用 `market.resolve_instrument`；
- 调用历史价格能力；
- 标准化 Observation；
- 调用 Python 分析能力；
- 返回带数据时间的分析结果。

### 场景三：市场整体问题

```text
用户：最近中国 A 股为什么波动比较大？
```

期望：

- 不要求股票代码；
- 可以查询市场和新闻数据；
- 根据已有 Observation 分析；
- 数据不完整时说明限制。

### 场景四：跨市场问题

```text
用户：美国非农数据对中国 A 股有什么影响？
```

期望：

- 识别宏观事件和中国 A 股市场两个实体；
- 不要求用户指定股票；
- 动态选择宏观、汇率、利率、A 股和历史事件能力；
- 必要时使用有界 ReAct；
- 最终回答包含影响传导链、可能受影响的市场维度和数据限制；
- 不生成固定 `cross_market_route` 作为强制前置条件。

### 场景五：上下文引用

```text
用户：刚才提到的那只股票最近风险怎么样？
```

期望：

- 从当前会话解析实体；
- 若只有一个明确候选，直接继续；
- 若存在多个候选，才向用户提问；
- 不要求用户重新输入所有信息。

### 场景六：用户持仓分析

```text
用户：结合我的持仓分析一下风险。
```

期望：

- 调用 Java `portfolio` 能力；
- 校验用户身份和权限；
- 不直接访问 Java 数据库；
- 分析持仓集中度、行业暴露和风险指标；
- 普通分析不要求保存确认。

### 场景七：高风险操作

```text
用户：根据这个分析直接帮我调仓。
```

期望：

- 可以先分析；
- 任何真实副作用操作必须单独确认；
- 未确认前不得调用交易执行能力；
- 当前阶段如果没有交易工具，应明确说明暂不支持。

### 场景八：工具错误

期望：

- 解析 MCP 返回体中的业务错误；
- 创建 `FAILED` Observation；
- 按策略重试或降级；
- 不把错误对象交给模型伪装成正常数据；
- 最终回答明确说明数据不可用。

---

## 17. 开发实施顺序

### 阶段一：主流程语义修正

- 保留现有 LangGraph 和 Mem0；
- 将 Root Graph 调整为 Agent Loop；
- 保留 `QueryIntent`，但取消其固定路由职责；
- 增加 `AgentAction`；
- 删除“缺少股票代码就统一中断”的逻辑；
- 删除“普通分析结束统一询问是否保存”的逻辑；
- 增加直接回答路径；
- 增加多工具连续调用路径。

### 阶段二：工具和分析边界固化

- 统一 MCP 和 Java Tool Gateway；
- 完善 Observation Normalizer；
- 统一处理 `error: true` 业务错误；
- 确认 Tool 白名单和参数 Schema；
- 确保 Skill 只消费标准化输入；
- 确保 Python Analysis Capability 不查询数据。

### 阶段三：上下文和记忆完善

- 完成上下文引用解析；
- 完成 Mem0 首尾读写；
- 完成 Checkpointer 恢复；
- 区分会话状态、分析历史和长期记忆；
- 完成普通分析自动结束机制。

### 阶段四：复杂问题和有界 ReAct

- 支持跨市场问题；
- 支持宏观事件问题；
- 支持多实体问题；
- 支持动态工具选择；
- 设置 ReAct 轮次和预算；
- 处理部分数据缺失和多工具失败。

### 阶段五：回归验收

- 运行所有现有测试；
- 增加金融对话场景测试；
- 增加无股票代码测试；
- 增加多实体和上下文引用测试；
- 增加工具错误和预算耗尽测试；
- 增加 Checkpointer 恢复测试；
- 增加普通回答不写长期记忆的测试。

---

## 18. 必须遵守的工程约束

1. Agent 不得直接访问数据库。
2. Agent 不得直接调用 MCP 原始客户端。
3. MCP 必须通过 Tool Gateway 接入。
4. Java 用户数据必须通过 Java API 接入。
5. Skill 不负责查询数据。
6. Analysis Capability 不依赖 LangGraph、LangChain、Mem0 或 MCP。
7. QueryIntent 不直接决定工具。
8. QueryIntent 不直接触发 interrupt。
9. 没有股票代码不代表无法分析。
10. 普通分析不要求用户确认保存。
11. 所有工具结果必须先标准化为 Observation。
12. 工具业务错误不得被当成正常响应。
13. ReAct 必须有界。
14. Checkpointer 不等于长期记忆。
15. 未完成的目标不得被伪装成已完成。
16. 数据不足时必须显式返回限制。
17. 当前阶段不得以引入新 Agent 平台替代已有问题修复。
18. 当前阶段不实现 Letta、Hermes、Phoenix 或其他新增组件。

---

## 19. 当前交付标准

本需求文档对应的当前版本完成后，系统至少应具备以下行为：

```text
用户可以自然语言提问
  → Agent 判断是否直接回答或调用工具
  → 工具通过 Gateway 执行
  → 工具结果统一为 Observation
  → Agent 根据结果决定是否继续
  → Analysis Capability 完成确定性分析
  → 模型生成最终回答
  → 普通分析直接结束
```

必须能够处理：

- 单股票问题；
- 多股票问题；
- 市场和行业问题；
- 宏观问题；
- 跨市场影响问题；
- 用户持仓问题；
- 一般金融知识问题；
- 连续上下文问题；
- 数据不完整和工具失败问题。

最终交付的重点不是增加更多固定 Route，而是证明 Agent 能够在金融领域内根据用户问题动态选择下一步行动，并且在工具、数据、权限和预算约束下稳定完成对话。

---

## 20. 后续 Letta 迁移要求

Letta 不属于当前实施范围，但当前代码需要保留迁移可能性。

迁移时可能替换：

```text
LangGraph Agent Runtime
Mem0 Memory Provider
当前对话状态管理方式
```

迁移时必须保持稳定：

```text
MCP Tool 契约
Java Data API 契约
Observation 契约
AnalysisInput / AnalysisResult 契约
金融分析 Skill 契约
用户权限约束
高风险确认规则
```

因此当前开发不得把以下内容写死到 LangGraph 节点内部：

- 所有业务数据结构；
- 所有工具具体实现；
- 所有记忆存储细节；
- 所有分析能力实现；
- 所有用户权限判断。

当前目标是先把金融对话式 Agent 的行为和边界做正确，再决定是否用 Letta 重写 Agent Runtime，而不是提前同时维护两套运行时。
