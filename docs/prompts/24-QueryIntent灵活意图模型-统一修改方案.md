# StockWise QueryIntent 灵活意图模型
# Prompt 统一修改方案

> 版本：v1.0
> 状态：待实施
> 适用项目：stockwise-analysis
> 本文档合并原“Prompt 修改计划”和“可行性分析与修改建议”。
> **本文档只作为后续修改方案，不修改主 Prompt 23-全新股票分析系统-统一开发实施Prompt.md。**

---

## 1. 方案结论

当前 QueryIntent 的改造方向正确，但不能只修改意图对象本身。现有代码仍然在多个位置依赖单一 analysis_type 和单一 symbol，因此 QueryIntent 改造会影响 Query Agent、Entity Resolver、WorkflowPlan、DataRequirement、ReAct 路由、运行预算、AnalysisInput、AnalysisResult、最终总结和 interrupt 判断。

不建议一次性重构全部执行链，采用兼容迁移：

~~~text
第一阶段：扩展意图表达，保持旧执行链可运行
第二阶段：支持单目标多实体和动态中断
第三阶段：支持多目标子图、结果合并和独立预算
第四阶段：再评估远程 Skill 服务化
~~~

## 2. 当前主要问题

当前 QueryIntent 主要包含：

~~~text
analysis_type
symbol
scope
requires_portfolio
requires_confirmation
~~~

主要问题：

1. 把用户意图过早压缩成固定分析类型；
2. 默认把股票代码当成核心必填字段；
3. 一个问题只能表达一个分析目标；
4. 一个问题只能保存一个 symbol；
5. 市场、板块、行业、持仓问题容易被错误中断；
6. Query Agent 过早决定执行路径；
7. RuleBasedQueryAgent 依赖固定关键词；
8. WorkflowPlan 仍然是线性任务链；
9. AnalysisInput / AnalysisResult 仍以单次分析为中心；
10. 多目标情况下的预算、结果合并和失败隔离没有定义。

## 3. 核心设计原则

### 3.1 意图理解与流程规划分离

~~~text
用户输入
  → QueryIntent Agent：理解用户想做什么
  → Entity Resolver：解析股票、板块、市场、持仓等实体
  → Clarification Policy：判断是否真的无法继续
  → Workflow Planner：生成执行任务计划
  → Tool / MCP / Java API
  → Analysis Capability
  → Summary Model
~~~

职责边界：

- QueryIntent：语义层契约；
- EntityResolutionResult：实体解析契约；
- WorkflowPlan：执行层契约；
- DataRequirement：工具数据需求契约；
- AnalysisInput：单个分析目标的标准化输入；
- AnalysisResult：单个分析目标的结构化结果。

Agent 不得直接绕过 Gateway 调用 MCP、Java 或数据库。

### 3.2 不再默认要求股票代码

| 分析范围 | 是否默认需要股票代码 |
|---|---:|
| 单只股票分析 | 是，但可通过名称、上下文或 Resolver 解析 |
| 多股票比较 | 否，需要多个实体 |
| 板块分析 | 否，需要板块实体 |
| 市场趋势 | 否，可使用指数、成交量和市场宽度 |
| 行业分析 | 否，需要行业或板块实体 |
| 用户持仓分析 | 否，需要用户身份和 Java 持仓数据 |
| 综合市场分析 | 否 |

没有股票代码不应自动触发 interrupt。

### 3.3 自由性不等于无约束

LLM 可以自由理解用户目标、实体和表达方式，但必须：

- 输出结构化 JSON；
- 经过 Pydantic 校验；
- 不直接产生工具调用；
- 不编造股票代码或数据；
- 不因为不确定就强行要求股票代码；
- 不因为字段缺失就自动中断；
- 保留无法解析的原始实体和用户原话。

## 4. QueryIntent 新契约

建议调整为：

~~~python
class QueryIntent(BaseModel):
    request_summary: str
    goals: list[IntentGoal] = Field(default_factory=list)
    entities: list[IntentEntity] = Field(default_factory=list)
    time_range: TimeRange | None = None
    requested_dimensions: list[str] = Field(default_factory=list)
    output_preferences: dict[str, Any] = Field(default_factory=dict)
    conversation_references: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None
    confidence: float | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)
~~~

analysis_type 暂时不能立即删除。迁移阶段应将它保留为下游兼容字段或 execution_profile 的派生结果，而不是继续把它当作用户真实意图。

### 4.1 分析目标

~~~python
class IntentGoal(BaseModel):
    goal_id: str
    goal_type: str
    description: str
    entity_refs: list[str] = Field(default_factory=list)
    priority: int = 1
    requested_outputs: list[str] = Field(default_factory=list)
~~~

推荐的 goal_type：

~~~text
snapshot / trend / technical_analysis / fundamental_analysis /
valuation / comparison / sector_analysis / market_analysis /
portfolio_impact / risk_diagnosis / news_review / custom
~~~

这些是推荐类型，不应成为封闭枚举。新类型必须经过 Planner 映射后才能执行。

### 4.2 分析实体

~~~python
class IntentEntity(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    symbol: str | None = None
    market: str | None = None
    role: str | None = None
    resolution_status: str = "UNRESOLVED"
    attributes: dict[str, Any] = Field(default_factory=dict)
~~~

推荐的 entity_type：

~~~text
instrument / sector / industry / market / index /
portfolio / concept / macro / news_topic / unknown
~~~

暂时无法归类的实体必须保留为 unknown，不能丢弃。

### 4.3 时间范围

不建议长期使用 dict 表示时间范围：

~~~python
class TimeRange(BaseModel):
    start: str | None = None
    end: str | None = None
    period: str | None = None
    timezone: str = "Asia/Shanghai"
    is_relative: bool = False
~~~

“最近一个月”“今年以来”等相对时间，必须在规划阶段解析成明确范围，并保留原始表达。

## 5. Query Intent Agent Prompt 要求

角色定义：

> 你是股票领域的用户意图理解 Agent。你的任务是理解用户想完成的事情，识别多个目标、多个实体、时间范围、比较关系和上下文引用，并输出结构化意图。你不负责查询数据，不负责决定最终工具，也不要求每个问题必须包含股票代码。

Prompt 必须明确要求：

1. 一个问题可以有多个 goals；
2. 一个问题可以有多个 entities；
3. 股票代码只是实体的可选属性；
4. 支持市场、板块、行业、指数、持仓等非股票实体；
5. 支持“刚才那只”“这两个板块”等上下文引用；
6. 无法确认实体时保留名称并标记 UNRESOLVED；
7. clarification_needed 只能作为模型建议，不能直接控制 Graph；
8. clarification_question 必须说明缺少什么及其影响；
9. 不得输出工具名称、MCP 名称、数据库语句或虚构数据；
10. 不得把不确定实体直接转换成股票代码。

## 6. Entity Resolver 设计

resolve_entities 不能只在流程图中声明，必须定义输入、工具、输出和失败行为。

~~~python
class EntityResolutionResult(BaseModel):
    entity_id: str
    status: str  # RESOLVED / AMBIGUOUS / NOT_FOUND / NOT_REQUIRED
    selected: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None
    provenance: list[dict[str, Any]] = Field(default_factory=list)
~~~

规则：

- RESOLVED：继续流程；
- NOT_REQUIRED：例如市场趋势不需要单只股票；
- AMBIGUOUS：工具无法消歧时才允许中断；
- NOT_FOUND：返回结构化说明或部分结果；
- 不允许模型自行猜测代码；
- 股票名称解析应通过统一能力，例如 market.resolve_instrument；
- 板块、行业和概念若没有对应搜索能力，必须标记未解析，不得假装已经解析。

当前 MCP 主要覆盖股票和市场数据，板块搜索能力需要单独确认，不能把 market.get_industry_context 误当成板块搜索工具。

## 7. LangGraph 流程调整

### 7.1 Query Graph

现有流程：

~~~text
understand_request
→ check_missing_context
→ interrupt_for_clarification
→ build_data_requirements
~~~

目标流程：

~~~text
receive_request
→ understand_intent
→ resolve_conversation_references
→ resolve_entities
→ evaluate_clarification_need
→ interrupt_if_blocking
→ build_dynamic_workflow_plan
~~~

### 7.2 动态中断判断

LLM 不直接决定是否中断，增加代码策略节点：

~~~python
class ClarificationDecision(BaseModel):
    should_interrupt: bool
    reason: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    question: str | None = None
~~~

只在以下情况触发：

- 单一目标无法确定；
- 比较任务缺少比较对象；
- 实体对应多个候选且工具无法消歧；
- 上下文引用不存在；
- 敏感写入或真实副作用操作缺少确认。

以下情况不得中断：

- 市场趋势没有单只股票代码；
- 板块分析没有股票代码；
- 用户同时询问多个实体；
- 用户没有明确指定分析类型但目标可以推断；
- 非关键字段缺失但仍能输出部分结果。

### 7.3 动态数据需求

build_data_requirements 不再只读取单一 analysis_type，应根据：

~~~text
goals
entities
time_range
requested_dimensions
user_profile
~~~

生成一个或多个 DataRequirement。

## 8. analysis_type 兼容迁移

现有代码仍依赖 analysis_type，第一阶段不能直接删除：

~~~text
QueryIntent.goal_type
    ↓
ExecutionProfile / analysis_type
    ↓
WorkflowPlan、预算、Analysis Capability
~~~

过渡规则：

~~~text
goals 为空
→ market_snapshot

单一 goal
→ 映射到对应 execution profile

多个 goals
→ multi_goal / comprehensive，仅表示需要多目标编排
~~~

不能把多个目标简单压缩成一个综合结果后假装完成全部目标。第一阶段可以保留多个 goals 但限制执行范围，并在结果中明确未执行目标。

## 9. 多目标执行方案

当前 WorkflowPlan 是线性任务链，而多个 goals 需要明确执行策略。

### 9.1 第一阶段

允许 QueryIntent 输出多个 goals，但当前执行层只承诺：

- 单目标完整执行；
- 多目标完整识别；
- 多目标中选择明确的主目标执行；
- 未执行目标写入 limitations；
- 不得把未执行目标伪装成已完成。

### 9.2 第二阶段

增加：

~~~text
GoalSubgraph
GoalAnalysisResult
GoalResultMerger
~~~

~~~python
class GoalAnalysisResult(BaseModel):
    goal_id: str
    status: str
    analysis_result: dict[str, Any] | None = None
    limitations: list[str] = Field(default_factory=list)


class MultiGoalAnalysisResult(BaseModel):
    results: list[GoalAnalysisResult]
    overall_summary: str | None = None
    limitations: list[str] = Field(default_factory=list)
~~~

需要明确目标之间是串行还是并行、是否共享 Observation、如何合并预算、一个目标失败是否影响其他目标。

## 10. RuleBasedQueryAgent 定位

RuleBasedQueryAgent 只作为 LLM 不可用时的最小降级实现，不承担完整自然语言理解职责。

允许它做：

- 提取股票代码；
- 提取少量明显名称；
- 识别持仓、市场、板块等基础词；
- 保留原始用户文本；
- 生成低置信度基础意图；
- 标记无法解析的实体。

不要求它完整识别复杂多目标、多实体语义。复杂场景应输出低置信度结果并交给后续 LLM 或 Resolver，而不是继续堆叠大量 if/elif。

## 11. 预算分配策略

这里的预算是一次 Agent 运行的系统资源预算，不是用户的投资金额。

预算可以限制：

- ReAct 轮数；
- MCP、Java 和其他 Tool 调用次数；
- 子图运行时间；
- 总请求时间；
- LLM 调用次数或 Token；
- 分析能力调用时间。

当前 AnalysisBudget 可以继续保留，但多目标之后不能只按一个 analysis_type 分配：

~~~text
总请求预算
├─ QueryIntent / Planner 预算
├─ 目标一数据预算
├─ 目标二数据预算
├─ Analysis Capability 预算
└─ Summary / Merge 预算
~~~

预算耗尽必须停止继续调用，并返回 LIMITED，不得无限增加调用次数。

## 12. 持久化策略

删除“每次分析结束都询问是否保存”的固定流程，但区分：

~~~text
Checkpointer
→ 自动保存 LangGraph 运行状态，用于恢复，不询问用户

Analysis History
→ 普通分析结果自动记录，用于审计和历史查看

Long-term Memory
→ 用户偏好、风险偏好、投资目标等长期信息

Sensitive Action
→ 修改用户画像、风险偏好、交易计划或执行交易
~~~

普通分析完成后直接结束。只有长期记忆写入或敏感操作需要显式确认。

## 13. 分阶段实施计划

### 阶段一：兼容性修复

- 保留 analysis_type 作为兼容字段；
- 增加 goals 和 entities；
- 更新 LLM Prompt；
- RuleBased 只做最小兜底；
- 暂不实现完整多目标执行；
- 增加多实体和无股票代码意图测试。

验收：现有全量测试继续通过，旧流程不因 QueryIntent 扩展而中断。

### 阶段二：单目标多实体和动态中断

- 实现 EntityResolutionResult；
- 增加股票名称和上下文引用解析；
- 增加 ClarificationPolicy；
- 市场、板块、行业问题不再强制要求股票代码；
- 普通分析不再固定询问保存。

### 阶段三：多目标编排

- WorkflowPlan 支持分支或目标子图；
- AnalysisInput / AnalysisResult 支持 goal_id；
- 预算支持按目标分配；
- Summary 支持多结果合并；
- 定义串行、并行和失败隔离策略。

### 阶段四：可选远程分析能力

AnalysisCapabilityAdapter 先使用本地 Python 实现：

~~~text
AnalysisCapabilityAdapter
├─ PythonAnalysisCapabilityAdapter   当前实现
└─ RemoteSkillAdapter                未来可选
~~~

远程 Skill 服务化不应成为当前 QueryIntent 或多目标编排的强制前置条件。

## 14. 代码修改范围

~~~text
stockwise-analysis/src/stockwise_analysis/
├─ runtimes/langgraph/agents/query_agent.py
│  ├─ 重构 QueryIntent
│  ├─ 重写 Query Intent System Prompt
│  ├─ 扩展 LLM 输出解析
│  └─ 简化 RuleBasedQueryAgent
├─ runtimes/langgraph/graphs/query_graph.py
│  ├─ 增加上下文引用解析
│  ├─ 增加实体解析节点
│  └─ 增加动态中断策略节点
├─ runtimes/langgraph/nodes/nodes.py
│  ├─ 删除固定 symbol 缺失判断
│  ├─ 按 goals/entities 生成数据需求
│  └─ 移除普通分析固定保存确认
├─ contracts/
│  ├─ QueryIntent 相关契约
│  ├─ EntityResolutionResult
│  └─ ClarificationDecision
└─ tests/
   ├─ 单股票意图测试
   ├─ 多股票比较测试
   ├─ 市场/板块无代码测试
   ├─ 上下文引用测试
   ├─ 实体歧义中断测试
   ├─ LLM 降级测试
   └─ 多目标限制和预算测试
~~~

## 15. 验收标准

必须通过：

1. 单只股票问题可以正常生成意图并执行；
2. 多股票比较不会被压缩成单一 symbol；
3. 板块分析没有股票代码也可以继续；
4. 市场趋势没有股票代码也可以继续；
5. 持仓分析通过 Java 数据能力获取用户持仓；
6. “刚才那只股票”等上下文引用可以解析；
7. 无法消歧时才触发 interrupt；
8. 普通分析结束不再询问是否保存；
9. Checkpointer 继续自动保存和恢复；
10. Query Agent 不直接调用 Tool、MCP 或 Java API；
11. LLM 失败时 RuleBased 降级不会导致主流程崩溃；
12. MCP 数据缺失、工具失败和预算耗尽都能返回结构化状态。

不允许出现：

- 没有股票代码就统一要求用户补充；
- 一个问题只能生成一个分析目标；
- 一个问题只能保存一个 symbol；
- RuleBased Agent 直接覆盖 LLM 的多目标结果；
- QueryIntent Agent 直接决定 MCP 工具；
- 普通分析每次都触发保存确认；
- 为满足固定枚举而丢弃用户原始意图；
- 将尚未执行的目标伪装成已完成；
- 将多个目标无条件压缩成 comprehensive；
- 强制引入远程 Skill 服务作为当前阶段前置依赖。

## 16. 测试矩阵

| 场景 | 期望结果 |
|---|---|
| 单股票技术分析 | 识别单目标并正常执行 |
| 多股票比较 | 生成多个实体，不覆盖为单一 symbol |
| 板块趋势 | 不要求股票代码 |
| 市场整体趋势 | 不要求股票代码 |
| 用户持仓分析 | 调用 Java 持仓能力 |
| “刚才那只股票” | 使用会话上下文解析 |
| 股票名称多候选 | 返回候选并 interrupt |
| 实体不存在 | 结构化 NOT_FOUND 或部分结果 |
| LLM 返回非法 JSON | RuleBased 降级 |
| MCP 服务失败 | Observation FAILED / LIMITED |
| 预算耗尽 | 停止调用并返回 LIMITED |
| Checkpointer 恢复 | 不重复执行已完成步骤 |
| 普通分析结束 | 不触发保存确认 |
| 用户修改风险偏好 | 触发显式确认 |

## 17. 待最终确认的设计决策

1. 第一阶段是否只支持多目标识别，暂不完整执行多目标；
2. analysis_type 是否正式更名为 execution_profile；
3. 板块和行业实体是否增加专用解析能力；
4. 多目标执行采用串行子图还是并行子图；
5. Analysis History 由 Python 保存还是通过 Java API 保存；
6. 远程 Skill 是否仅作为未来 Adapter 实现；
7. 正式 Prompt 是否升级为 v3.2。

## 18. 最终定位

~~~text
QueryIntent Agent
= 理解用户想做什么

Entity Resolver
= 确认用户提到的对象是什么

Workflow Planner
= 决定如何完成这些目标

LangGraph
= 控制状态、工具、预算、中断和恢复

MCP / Java API
= 提供外部业务数据

Analysis Capability
= 对标准化数据进行计算和分析

Summary Model
= 将结构化结果转为用户可理解的回答
~~~

本方案的目标不是让 Agent 无限制自由调用系统，而是让它能够自由理解股票领域问题，再由确定性的 Planner、预算、Tool Gateway 和数据契约约束执行过程。
