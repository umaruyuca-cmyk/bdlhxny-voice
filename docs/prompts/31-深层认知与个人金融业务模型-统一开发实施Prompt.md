# StockWise 深层认知内核 + 个人金融业务模型
# 统一开发实施 Prompt

> 文档状态：开发执行稿 v1.1（吸收 33 号修订审查后的工程校正版）
>
> 适用项目：`stockwise-analysis`，以及必要的 Java 用户数据接口
>
> 目标：在不中断现有股票分析能力的前提下，建立“深层认知内核 ↔ 金融领域运行时”的稳定边界，并完成首个端到端垂直切片
>
> 实施策略：契约先行、薄层切分、垂直验证、渐进迁移
>
> 当前阶段：只读金融助手，不下单、不调仓、不划转资金、不修改账户

---

## 0. 如何使用本 Prompt

你是负责 StockWise 架构演进的高级 Python/LangGraph 工程师。请在现有仓库上实施本 Prompt，不要另起一个脱离当前代码的演示项目。

开始开发前必须完整阅读：

1. `docs/architecture/28-深层认知模型-架构与处理逻辑.md`
2. `docs/architecture/29-个人金融业务模型-架构与处理逻辑.md`
3. `docs/reviews/30-深层认知与金融业务模型-审查回归文档.md`
4. `docs/prompts/26-StockWise金融随身管家-需求更新版.md`
5. `stockwise-analysis/src/stockwise_analysis/runtimes/langgraph/graphs/root_graph.py`
6. `stockwise-analysis/src/stockwise_analysis/runtimes/langgraph/graphs/query_graph.py`
7. `stockwise-analysis/src/stockwise_analysis/runtimes/langgraph/graphs/market_data_graph.py`
8. `stockwise-analysis/src/stockwise_analysis/runtimes/langgraph/graphs/state.py`
9. `stockwise-analysis/src/stockwise_analysis/tools/capabilities.py`
10. `stockwise-analysis/src/stockwise_analysis/tools/requirement_planner.py`

本 Prompt 不授权一次性重写整个系统。每个阶段必须独立可测试、可回滚，并保留当前 API 和现有分析能力。

强制阶段停止规则：

1. 每个开发任务默认只允许执行一个阶段；
2. 阶段 0（审计）和阶段 1（纯契约）可以在同一任务内连续完成；
3. 其他阶段完成代码、测试、迁移矩阵和交付报告后必须停止；
4. 除非用户明确授权继续，否则不得自动进入下一阶段；
5. 不得以“最终目标尚未完成”为理由跨越阶段验收门。

开发任务必须按下列批次拆分，禁止把相邻阶段合并成一个实现任务：

| 开发任务 | 允许范围 |
|---|---|
| A | 阶段 0 + 阶段 1（唯一允许合并的批次） |
| B | 阶段 2 |
| C | 阶段 3 |
| D | 阶段 4 |
| E | 阶段 5 |
| F | 阶段 6 |
| G | 阶段 7 |

任何评审稿、执行记录或后续 Prompt 若将“阶段 3-4”“阶段 5-6”写成同一轮，均应按本表拆回独立任务和独立验收。

---

## 1. 文档优先级

安全、身份、权限、隐私和只读约束出现冲突时，按以下优先级执行：

1. 用户在当前开发任务中的明确要求；
2. 26 号 v2.1 中不可放宽的身份、安全、数据质量、权限和外部金融只读约束；
3. 本 31 号统一开发实施 Prompt；
4. 28/29 号目标架构；
5. 30/32/33 号审查文档中的风险提示；
6. 旧架构和旧 Prompt。

架构边界、开发顺序和迁移方式出现冲突时，按以下优先级执行：

1. 用户在当前开发任务中的明确要求；
2. 本 31 号统一开发实施 Prompt；
3. 28/29 号目标架构；
4. 26 号 v2.1 需求；
5. 30/32/33 号审查文档；
6. 旧架构和旧 Prompt。

任何低优先级文档都不得放宽高优先级安全约束。评审文档中的仓库状态、测试数量和行号只是带时间点的审计证据，执行时必须重新核对，不能作为永久代码事实。

30 号文档的以下内容在本 Prompt 中已经修正：

- 当前代码基线不能只看提交 `42b0722`，必须以实际工作区为准；
- 28 号完整 `NextAction` 是 9 种，不是 7 种；
- Belief 只能降低幻觉风险，不能宣称“根治幻觉”；
- v2.1 需求已经定义四时点 Guardrails，当前问题是代码尚未完整实现；
- 不采用“先继续做大旧 Root Graph，再整体拆分”的顺序；
- 先建立薄契约边界，再逐步迁移功能，避免二次返工。

---

## 2. 当前代码事实

开始编码前必须通过只读检查重新确认当前工作区，不能假设仓库等于某个历史提交。

当前已知已有能力包括：

- FastAPI + LangGraph；
- `RootState` 和 Checkpointer；
- `direct_response / single_capability / agent_loop` 执行模式；
- Query Graph 和 Market Data Graph；
- `CapabilityRegistry`；
- `CapabilityRequirementPlanner`；
- 每轮 `capability_candidates`；
- 工具执行前白名单检查；
- 预算控制；
- `Observation`、Normalizer、Provenance 和 DataQuality；
- `COMPLETE / PARTIAL / LIMITED` 覆盖率判断；
- MCP Gateway、Java Data Adapter、Web Search Adapter；
- Python Analysis Capability；
- Mem0/NoOp Memory；
- Analysis History；
- 多轮 `thread_id` 与单次 `run_id` 分离。

当前主要缺失包括：

- 深层认知内核和通用 `CognitiveState`；
- `DomainRequest / DomainOutcome` 边界；
- 股票研究的独立结构化结果；
- `SuitabilityEngine`；
- 结构化 Belief/Goal/Uncertainty；
- 完整的 Plan/Action/Data/Response Guardrails；
- 通用 Task/Commitment/Scheduler；
- 主动事件入口；
- CommunicationPlan + Response Verification。

当前股票执行链还有以下迁移事实，阶段 2 不得忽略：

- `resolve_instrument`、`assemble_analysis`、`run_analysis` 和 `evaluate_market_data` 当前接收 `RootState`，并通过 `_complete_current_task` 读写旧 `workflow_plan/current_task_id`；
- 当前不存在可直接复用的 `build_stock_research_result` 节点，该构建器属于阶段 3 的新增实现；
- 当前 `AnalysisResult` 只有部分字段可映射到 `StockResearchResult`，基本面、估值、情景、证据链和可信度策略不能假装已经完整；
- Java Data Adapter 在未配置真实 Java 服务时可能返回带 `is_mock` 或 `mock-java` Provenance 的示例账户数据，不能视为用户真实持仓。

开发时先重新审计，输出“已完成 / 部分完成 / 未完成”矩阵，禁止重复实现现有能力。

---

## 3. 总体目标

目标架构：

```text
InputEvent
  → Cognitive Kernel
      → NextAction
          ├─ RESPOND
          ├─ ASK_USER
          ├─ INVOKE_DOMAIN
          ├─ RETRIEVE_MEMORY
          ├─ CREATE_TASK
          ├─ UPDATE_TASK
          ├─ WAIT
          ├─ NOTIFY
          └─ DO_NOTHING

INVOKE_DOMAIN
  → FinancialDomainRequest
  → Finance Runtime
      → Financial Skills
      → Toolsets
      → Unified Capabilities
      → Observation
      → Deterministic Analysis
      → Suitability
      → FinancialDomainOutcome
  → Cognitive Kernel
  → Communication / Task / Wait / Notify
```

第一轮开发不要求完整实现 9 种行动。目标契约必须支持 9 种，首个垂直切片只启用：

```text
RESPOND
ASK_USER
INVOKE_DOMAIN
```

`RETRIEVE_MEMORY / CREATE_TASK / UPDATE_TASK / WAIT / NOTIFY / DO_NOTHING` 保留在类型中，但默认由 Policy 禁用，直到有真实场景、持久化语义和验收测试。

当用户提出“条件合适时帮我看着”等持续任务请求，而 Task/Scheduler 尚未启用时，系统必须返回结构化 `ACTION_NOT_ENABLED`，并明确说明当前不能真正建立观察任务；禁止只回复“好的”。

---

## 4. 本次开发范围

### 4.1 目标架构总交付（非单次开发任务）

1. 当前工作区基线审计；
2. 通用领域请求/结果契约；
3. 金融领域请求/结果契约；
4. 股票研究结构化结果契约；
5. 适配性判断契约；
6. 最小 Cognitive State 和 Cognitive Graph；
7. Finance Runtime 的薄适配层；
8. 当前股票分析流程到 `StockResearchResult` 的适配；
9. `SuitabilityEngine v0`；
10. 一个完整的“股票是否适合当前用户”端到端场景；
11. 保持当前 API 兼容；
12. 单元测试、Graph 测试、契约测试和回归测试；
13. 更新架构落地状态文档。

以上是本开发计划全部阶段的总交付范围，不表示一个开发任务必须一次完成。实际执行严格遵循 §0 的阶段停止规则。

### 4.2 可以作为第二阶段完成

1. 最小 `FinancialTask`；
2. `CREATE_TASK / WAIT` 的数据库持久化；
3. 一种估值或价格观察任务；
4. Scheduler 唤醒；
5. 通知策略，但不接入多渠道发送。

### 4.3 本次禁止扩展

- 完整商业银行级 Belief 管理平台；
- 多领域插件平台；
- 任意动态加载第三方 Skill；
- LLM 直接调用原始 MCP Tools；
- 交易、下单、调仓、撤单、转账；
- 自动修改风险画像；
- 自动写入未确认的长期偏好；
- 为了新架构删除旧 API；
- 一次性替换全部 Root Graph；
- 直接依赖 Hermes Runtime。

Hermes 只作为窄核心、Skill、Toolset、Scheduler 和隔离能力的架构参考，不作为运行时依赖。

---

## 5. 不可变架构原则

### 5.1 认知和金融分离

认知内核负责：

- 当前发生了什么；
- 用户想完成什么；
- 有哪些未知和约束；
- 下一步应该回答、追问、调用领域、建任务还是等待；
- 如何向用户表达；
- 是否需要持续跟进。

金融领域负责：

- 金融问题如何分解；
- 需要哪些金融状态和数据；
- 选择哪些 Financial Skills；
- 如何计算；
- 如何评估金融风险和适配性；
- 返回什么结构化领域结果。

### 5.2 数据和分析分离

所有外部数据：

```text
Unified Capability
→ Gateway
→ MCP / Java / Web
→ Observation Normalizer
→ Observation
```

所有确定性分析：

```text
Observation
→ AnalysisInput / SkillInput
→ domain/
→ CalculationResult / SkillResult
```

### 5.3 客观研究和用户适配分离

必须分别回答：

```text
资产本身怎么样？
它当前是否适合这个用户？
```

`StockResearchResult` 不直接产生个性化买卖建议。个性化结论只能由 Suitability 层结合用户状态产生。

### 5.4 证据和表达分离

回复模型只能使用结构化领域结果和公开证据，不得直接读取原始 MCP 响应，也不得生成领域结果中不存在的新事实。

### 5.5 外部金融只读和最小权限

所有第一阶段外部金融和账户 Capability 必须只读。账户数据按本次目标最小化读取。

允许在 Policy 控制下写入系统内部运行数据，包括 Checkpoint、Conversation、Analysis/Decision History；Task 和长期 Memory 只有在对应阶段启用且满足确认策略后才允许写入。禁止修改账户、持仓、订单、资金和外部金融系统状态。

---

## 6. 阶段 0：基线审计与冻结

编码前完成以下检查：

1. `git status --short`，确认并保护用户现有改动；
2. 列出当前 Graph、State、Agent、Capability、Adapter、Memory、History；
3. 检查当前测试数量和结果；
4. 检查 26 号需求已实现、部分实现和未实现项；
5. 检查 30 号审查文档中已过期的判断；
6. 输出迁移矩阵。

迁移矩阵格式：

| 目标能力 | 当前实现 | 状态 | 本轮动作 | 回归测试 |
|---|---|---|---|---|
| DomainRequest | 无 | 未完成 | 新增契约 | contract test |
| Capability Registry | 已有 | 完成 | 复用 | existing tests |
| StockResearchResult | AnalysisResult 部分覆盖 | 部分完成 | 新增适配 | stock result test |
| Suitability | 无 | 未完成 | v0 | suitability tests |

阶段 0 不修改业务逻辑。完成矩阵后才进入阶段 1。

---

## 7. 阶段 1：建立领域边界契约

### 7.1 通用领域契约

建议新增：

```text
src/stockwise_analysis/domains/contracts.py
src/stockwise_analysis/domains/registry.py
```

最低契约。以下为边界模型示意，实际实现应使用 `StrEnum`、`Field(default_factory=...)` 和 Pydantic 校验器：

```python
from datetime import datetime
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field, JsonValue, model_validator


class DomainOperation(StrEnum):
    READ_MARKET_DATA = "READ_MARKET_DATA"
    READ_PORTFOLIO = "READ_PORTFOLIO"
    READ_PROFILE = "READ_PROFILE"
    READ_FINANCIAL_GOALS = "READ_FINANCIAL_GOALS"
    RUN_ANALYSIS = "RUN_ANALYSIS"
    PROPOSE_TASK = "PROPOSE_TASK"


class GoalRef(BaseModel):
    goal_id: str
    description: str
    source: Literal[
        "USER_EXPLICIT",
        "PROFILE_CONFIRMED",
        "MEMORY_CONFIRMED",
        "TASK",
        "INFERRED",
    ]


class DomainConstraint(BaseModel):
    constraint_id: str
    constraint_type: str
    description: str
    source: str
    materiality: Literal["LOW", "MEDIUM", "HIGH"]


class ContextRef(BaseModel):
    ref_type: str
    ref_id: str
    version: str | None = None


class DomainBudget(BaseModel):
    tool_call_limit: int
    runtime_seconds: int
    model_call_limit: int = 0


class DomainFact(BaseModel):
    fact_id: str
    statement: str
    value: JsonValue = None
    source_refs: list[str] = Field(default_factory=list)
    directness: Literal["DIRECT", "DERIVED", "INFERRED"]


class DomainFinding(BaseModel):
    finding_id: str
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class DomainRisk(BaseModel):
    risk_id: str
    description: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    evidence_ids: list[str] = Field(default_factory=list)


class DomainConflict(BaseModel):
    conflict_id: str
    description: str
    left_refs: list[str]
    right_refs: list[str]
    materiality: Literal["LOW", "MEDIUM", "HIGH"]


class ConfidenceAssessment(BaseModel):
    level: Literal["HIGH", "MEDIUM", "LOW"]
    reasons: list[str]
    coverage_status: Literal["COMPLETE", "PARTIAL", "LIMITED"]


class RequiredUserDecision(BaseModel):
    decision_id: str
    question: str
    reason: str
    allowed_choices: list[str]


class SuggestedFollowup(BaseModel):
    followup_type: str
    description: str
    trigger: JsonValue = None


class DomainRequest(BaseModel):
    request_id: str
    domain: str
    authenticated_user_id: str
    objective: str
    goals: list[GoalRef] = Field(default_factory=list)
    constraints: list[DomainConstraint] = Field(default_factory=list)
    success_criteria: list[str]
    context_refs: list[ContextRef] = Field(default_factory=list)
    authorized_operations: set[DomainOperation]
    budget: DomainBudget


class DomainOutcome(BaseModel):
    request_id: str
    domain: str
    status: Literal[
        "COMPLETE",
        "PARTIAL",
        "LIMITED",
        "FAILED",
        "WAITING_USER",
    ]
    established_facts: list[DomainFact] = Field(default_factory=list)
    findings: list[DomainFinding] = Field(default_factory=list)
    risks: list[DomainRisk] = Field(default_factory=list)
    conflicts: list[DomainConflict] = Field(default_factory=list)
    confidence: ConfidenceAssessment
    limitations: list[str] = Field(default_factory=list)
    required_user_decisions: list[RequiredUserDecision] = Field(default_factory=list)
    suggested_followups: list[SuggestedFollowup] = Field(default_factory=list)
```

要求：

- `authenticated_user_id` 只由服务端认证上下文提供；
- 契约必须可序列化、可写入 Checkpointer；
- `DomainOutcome` 不包含最终聊天文案；
- `status` 不能因 LLM 表达而改变；
- `authorized_operations` 表示领域授权操作，不得命名为 `allowed_actions`，避免与认知行动混淆；
- 跨层边界不得退回 `list[dict]` 或无约束 `dict`；Graph 内部如需字典状态，只能由这些模型 `model_dump()` 得到；
- 不保存模型隐藏思维链。

### 7.2 认知行动契约

代码中统一使用 `CognitiveAction`。`NextAction` 只作为架构概念名称，不再创建第二个同义模型；禁止继续复用旧 `AgentAction` 表达认知层动作。

```python
class CognitiveActionType(StrEnum):
    RESPOND = "RESPOND"
    ASK_USER = "ASK_USER"
    INVOKE_DOMAIN = "INVOKE_DOMAIN"
    RETRIEVE_MEMORY = "RETRIEVE_MEMORY"
    CREATE_TASK = "CREATE_TASK"
    UPDATE_TASK = "UPDATE_TASK"
    WAIT = "WAIT"
    NOTIFY = "NOTIFY"
    DO_NOTHING = "DO_NOTHING"


class CognitiveAction(BaseModel):
    action_type: CognitiveActionType
    reason_code: str
    reason: str
    related_goal_ids: list[str] = Field(default_factory=list)
    domain_request: DomainRequest | None = None
    task_spec_ref: str | None = None

    @model_validator(mode="after")
    def validate_payload(self):
        # INVOKE_DOMAIN 必须携带 domain_request；其他动作不得偷带领域请求。
        ...
```

第一阶段 Action Policy 只允许 `RESPOND / ASK_USER / INVOKE_DOMAIN`。其余枚举值必须返回稳定审计码 `ACTION_NOT_ENABLED`，不能静默降级为 `RESPOND`。

### 7.3 金融领域契约

建议新增：

```text
src/stockwise_analysis/domains/finance/contracts.py
```

至少定义：

```text
FinancialDomainRequest
FinancialDomainOutcome
FinancialSnapshot
StockResearchResult
SuitabilityAssessment
EvidenceFact
Finding
EvidenceConflict
Scenario
```

`FinancialDomainRequest` 应扩展 `DomainRequest`，增加 `financial_intent`、金融实体和 `requires_financial_snapshot`；`FinancialDomainOutcome` 应扩展 `DomainOutcome`，使用显式类型增加 `stock_research_result`、`suitability`、`portfolio_impact`、`goal_impact` 和 `liquidity_impact`。禁止复制一套语义相同但字段不同的基类。

### 7.4 EvidenceFact

```python
class EvidenceFact(BaseModel):
    fact_id: str
    statement: str
    value: JsonValue = None
    source: str
    source_time: datetime | None
    retrieved_at: datetime
    directness: Literal["DIRECT", "DERIVED", "INFERRED"]
    quality: Literal["HIGH", "MEDIUM", "LOW", "INVALID"]
```

禁止使用没有证据来源的 `CONFIRMED`。第一阶段可先用 `directness + quality`，不必立即建立完整持久化 Belief 引擎。

`EvidenceFact` 是金融领域对通用 `DomainFact` 的扩展，不得重新定义语义冲突的同名字段。金融 `Finding` 同理应扩展或兼容 `DomainFinding`。

第一阶段的证据生命周期必须明确区分：

- 本次运行中的 `EvidenceFact / Finding / EvidenceConflict` 作为结构化 State 对象，随当前运行的 Checkpointer 保存；
- 需要跨会话追溯的研究结果、证据快照、决策依据和审计信息写入 Analysis/Decision History，并保留来源时间和版本；
- Mem0 只保存用户明确确认过的稳定偏好、目标和长期约束，不承担行情、研究证据或一次性分析结论的跨会话存储；
- 禁止把临时行情、原始 MCP 响应、未确认推断、短期 Finding 自动写入 Mem0。

### 7.5 Finding

```python
class Finding(BaseModel):
    finding_id: str
    statement: str
    evidence_ids: list[str]
    calculation_ids: list[str]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    invalidation_conditions: list[str]
```

可信度由策略根据覆盖率、时效、来源质量和冲突计算。禁止让 LLM自由输出百分比可信度。

### 7.6 阶段验收

- 所有契约有 Pydantic 验证测试；
- 非法状态和缺失身份被拒绝；
- 契约序列化/反序列化无损；
- `DomainOutcome` 不允许混入最终回复字段；
- `CognitiveAction` 为唯一认知行动模型，`INVOKE_DOMAIN` 载荷校验有效；
- `allowed_actions` 不再作为领域权限字段；
- 跨层契约不存在无约束 `dict` 和 `list[dict]`；
- 当前代码没有被切换到新 Graph。

---

## 8. 阶段 2：Finance Runtime 薄适配层

### 8.1 目标

不要立即重写现有股票业务能力，但也不得把依赖 `RootState/workflow_plan` 的旧节点误称为纯领域节点。先抽取最小领域核心，再由旧流程包装器和新 Finance Runtime 分别复用。

建议新增：

```text
src/stockwise_analysis/domains/finance/runtime.py
src/stockwise_analysis/domains/finance/state.py
src/stockwise_analysis/domains/finance/adapter.py
src/stockwise_analysis/domains/finance/graphs/market_data_core_graph.py
src/stockwise_analysis/domains/finance/graphs/stock_research_graph.py
```

### 8.2 Finance Runtime 接口

```python
class FinanceRuntime(Protocol):
    async def execute(
        self,
        request: FinancialDomainRequest,
        *,
        context: DomainExecutionContext,
    ) -> FinancialDomainOutcome:
        ...
```

`DomainExecutionContext` 是服务端生成的最小执行上下文，不接收客户端任意字典：

```python
class DomainExecutionContext(BaseModel):
    run_id: str
    conversation_id: str | None
    authenticated_user_id: str
    requested_at: datetime
    deadline_at: datetime | None
    financial_snapshot_ref: ContextRef | None = None
```

Gateway、Registry、Repository、Memory 等运行依赖通过 `FinanceRuntime` 构造函数注入，不得塞入 `context`。

执行前必须验证 `request.authenticated_user_id == context.authenticated_user_id`；不一致时返回稳定鉴权错误并禁止读取 FinancialSnapshot。

第一版禁止调用当前完整 Root Graph。当前 Root Graph 包含 Query、Memory、Compose 和持久化职责，嵌套调用会重复理解、重复表达、重复写历史并可能污染 Checkpointer。

当前 `resolve_instrument / assemble_analysis / run_analysis / evaluate_market_data` 不是可直接调用的纯领域链：它们接收 `RootState`，并会通过 `_complete_current_task` 修改旧工作流任务。阶段 2 必须采用“核心抽取 + 双包装”方式：

```text
共享领域核心（不得感知 workflow_plan/current_task_id）
resolve_instrument_core
→ MarketDataCoreGraph(MarketDataState)
→ assemble_analysis_core
→ run_analysis_core
       ├─ LegacyRootGraphWrapper：负责旧 _complete_current_task 和 RootState 投影
       └─ StockResearchGraph v0：负责 FinancialBusinessState 投影和领域结果封装
```

具体约束：

1. 新 `MarketDataCoreGraph` 使用领域专用 `MarketDataState`，不得读取或写入 `workflow_plan/current_task_id`；
2. 旧 Root Graph 通过薄 Wrapper 在核心执行前后处理旧任务完成语义，保持旧 API 行为；
3. 新 `StockResearchGraph v0` 复用同一核心，不复制一份节点拓扑，不手工串行调用带 LangGraph 路由语义的旧节点；
4. 阶段 2 尚未实现 `build_stock_research_result`。本阶段可以返回 `AnalysisResult` 兼容载荷及结构化 observations/coverage，阶段 3 再构建正式 `StockResearchResult`；
5. 不得通过伪造 `RootState`、`WorkflowPlan` 或 `current_task_id` 让新路径迁就旧节点副作用；
6. 适配链不得执行 `query_graph`、`compose_response`、`persist_memory` 或 `persist_history`；
7. 同步、无恢复需求的领域核心优先不配置 Checkpointer；如必须持久化子图，则使用独立 namespace/thread key，禁止与 Cognitive Graph 共用同一个顶层 Checkpoint State。

禁止将以下做法作为最终阶段 2 实现：

- 在 Finance Runtime 中直接 `invoke` 当前以 `RootState` 编译的 Market Data Graph；
- 复制一份现有 Market Data Graph 拓扑，仅把 State Schema 改名；
- 逐个手工调用现有 LangGraph 节点从而丢失 ReAct、条件边或重试语义。

### 8.3 状态边界

第一版允许通过适配器从现有 `RootState` 投影出最小 `FinancialBusinessState`：

```python
class FinancialBusinessState(TypedDict, total=False):
    domain_request: dict
    financial_snapshot: dict | None
    selected_skills: list[str]
    data_requirements: list[dict]
    capability_candidates: list[dict]
    observations: list[dict]
    coverage: dict
    stock_research_result: dict | None
    suitability: dict | None
    domain_outcome: dict | None
    status: str
    events: list[dict]
    errors: list[dict]
```

`FinancialBusinessState` 是 LangGraph 内部传输形态，以上 `dict` 必须来自对应 Pydantic 边界模型的 `model_dump()`，不能接收未验证的任意字典。

`FinancialBusinessState` 和 `MarketDataState` 均不得包含 `workflow_plan/current_task_id`。旧任务状态只存在于 `LegacyRootGraphWrapper` 一侧，领域核心完成状态通过显式 `CoreExecutionResult` 返回，不得调用 `_complete_current_task`。

不要在本阶段把完整用户账户、全部持仓历史或原始 MCP 响应复制到新 State。

### 8.4 阶段验收

- 相同股票请求通过 Adapter 后仍能获得与当前流程一致的数据覆盖；
- Adapter 返回合法 `FinancialDomainOutcome`；
- MCP 调用数量和预算不增加；
- 当前 API 行为保持兼容；
- Finance Runtime 不执行 Query、Compose、Memory/History 写入；
- Cognitive Graph 和领域子图的 Checkpoint 命名空间互不污染；
- 领域核心不 import `_complete_current_task`，不读写 `workflow_plan/current_task_id`；
- 旧 Root Graph Wrapper 与新 StockResearchGraph 对同一固定输入产生等价的核心 `AnalysisResult`、coverage 和 provenance；
- 代码中只有一份 Market Data 核心拓扑，旧新路径没有复制漂移；
- 原有测试全部通过。

---

## 9. 阶段 3：股票研究结果下沉

### 9.1 目标

将当前股票分析输出拆成客观研究结果，不再让股票分析节点直接承担个性化建议。

建议新增：

```text
src/stockwise_analysis/skills/registry.py
src/stockwise_analysis/skills/stock_research/spec.py
src/stockwise_analysis/skills/stock_research/adapter.py
src/stockwise_analysis/skills/stock_research/result_builder.py
```

第一阶段不要求立刻把当前 Graph 文件物理移动。先通过 Adapter 建立输出边界，等回归稳定后再移动拓扑。

### 9.2 StockResearchResult

至少包含：

```text
instrument
market_snapshot
fundamentals
valuation
technicals
money_flow
industry_context
events/news
scenarios
risks
evidence
coverage
confidence
limitations
```

阶段 3 开发前必须先提交并测试字段来源映射，不能把“原始数据存在”等同于“研究结论已经存在”：

| 结果字段 | 当前可用来源 | 当前成熟度 | 阶段 3 必须补齐 |
|---|---|---|---|
| `instrument` | 标的解析结果 | 直接可用 | 统一标识、市场和名称校验 |
| `market_snapshot` | 行情 Observation | 直接可用 | 时效、来源和交易状态 |
| `technicals` | `AnalysisResult.calculated_indicators/signals` | 部分可用 | 指标计算引用和数据窗口 |
| `fundamentals` | financial Observation + `financial_found` | 明显不足 | 确定性指标、同比/趋势、缺失项和证据引用 |
| `valuation` | valuation Observation | 原始数据部分可用 | 估值口径、比较基准、日期和限制 |
| `money_flow` | money-flow Observation | 原始数据部分可用 | 结构化解释、时效和覆盖 |
| `industry_context` | industry Observation | 原始数据部分可用 | 行业比较、口径和冲突 |
| `events/news` | news/web Observation | 原始证据部分可用 | 事件去重、时间、来源质量和事实/观点区分 |
| `risks` | `risk_flags` + 数据质量 | 部分可用 | 研究风险、数据风险和用户风险分层 |
| `scenarios` | 无正式来源 | 未完成 | 独立 Bull/Base/Bear 或条件情景构建器；不得把技术 signals 改名冒充情景 |
| `evidence` | Observation provenance | 部分可用 | `EvidenceFact` 构建、去重、引用完整性和冲突保留 |
| `coverage` | 当前 coverage 模型 | 可复用 | 映射到各研究维度而非单一总状态 |
| `confidence` | 无统一策略 | 未完成 | 基于覆盖率、时效、来源质量和冲突的确定性策略 |
| `limitations` | errors/coverage/data quality | 部分可用 | 明确哪些结论不可得以及原因 |

直接映射、派生计算和新建能力必须在代码与测试中分别标识。缺失字段可以显式为 `NOT_AVAILABLE/LIMITED`，但不得用空对象填充后宣称完整研究。

### 9.3 分析要求

- 基本面不能只使用 `financial_found=True`；
- 每个重要结论必须引用 Evidence 或确定性 Calculation；
- `PARTIAL` 数据不能包装成完整研究；
- 估值、财务、技术和新闻冲突必须显式保留；
- 100 分启发式评分不得作为统一可信度；
- 研究结果不输出“适合你买入”之类个性化结论。
- `signals` 只能作为技术证据或情景输入，不能直接等同于 Bull/Base/Bear `Scenario`；
- `confidence` 由确定性 Policy 生成，并输出导致降级的因素，LLM 不参与最终可信度定级。

### 9.4 阶段验收

- market snapshot、technical、fundamental、valuation、comprehensive 均能构建合法结果；
- 缺财报时 fundamental 为 `LIMITED` 或清晰 `PARTIAL`；
- 每个 Finding 的 evidence ID 存在；
- 每个 Scenario 的假设、触发条件和 Evidence 引用存在；没有情景能力时显式 `LIMITED`；
- 字段来源映射测试能区分 DIRECT、DERIVED 和 NOT_AVAILABLE；
- 原有 AnalysisResult 可通过兼容 Adapter 继续服务旧 API。

---

## 10. 阶段 4：SuitabilityEngine v0

### 10.1 目标

实现“资产质量”和“用户适配性”分离的最小可用版本。

建议新增：

```text
src/stockwise_analysis/domains/finance/suitability.py
src/stockwise_analysis/domains/finance/policies/
```

### 10.2 输入

```text
StockResearchResult
FinancialSnapshot
User Risk Profile
Portfolio Positions
Relevant Financial Goals
Liquidity Snapshot
```

如果当前数据源只支持部分输入，必须在结果中标记 `INSUFFICIENT_INFORMATION` 或限制，不得用默认值伪造用户状态。

账户快照必须携带可判定的数据真实性元数据，例如 `data_mode: LIVE | USER_CONFIRMED | TEST_FIXTURE | MOCK | UNAVAILABLE`、`is_mock` 和 provenance。运行时只允许已认证数据源的 `LIVE` 数据，或用户在本轮明确提供并确认的 `USER_CONFIRMED` 数据，驱动真实用户的个性化适配结论：

- 默认节点未注入 Adapter 时可能得到空持仓，这表示 `UNAVAILABLE`，不表示用户没有持仓；
- Java Data Adapter 未连接真实服务时可能返回两条带 `mock-java` 来源的示例持仓，这表示 `MOCK`，不表示用户真实持仓；
- `MOCK`、`is_mock=true` 或 provenance 含 `mock-java` 时，真实请求必须返回 `INSUFFICIENT_INFORMATION`，且列出“账户数据为模拟数据”的限制；
- 自动化测试可以显式注入 `TEST_FIXTURE` FinancialSnapshot 验证集中度等规则，但 Fixture 必须由测试构造，不能依赖运行时隐式 mock；
- `USER_CONFIRMED` 必须记录确认时间、适用范围和用户来源，不能由模型推断产生；
- 生产和开发运行日志必须区分 `LIVE/USER_CONFIRMED/TEST_FIXTURE/MOCK/UNAVAILABLE`，禁止静默把 mock 升格为 live。

Financial Goal 和重大约束的来源优先级固定为：

```text
本轮用户明确输入（USER_EXPLICIT）
→ 结构化 FinancialGoal（PROFILE_CONFIRMED）
→ 用户明确确认过的长期记忆（MEMORY_CONFIRMED）
→ 无可信来源时视为 UNKNOWN
```

`INFERRED` 目标可以用于提出澄清问题，不能直接驱动高影响个性化结论。“半年后要买房”的验收场景第一阶段使用本轮用户明确输入；在 FinancialGoal 数据能力上线前，不得假装从账户系统读取到了该目标。

### 10.3 输出

```python
class PortfolioImpact(BaseModel):
    current_exposure: JsonValue
    projected_exposure: JsonValue
    rule_ids: list[str]


class GoalImpact(BaseModel):
    affected_goal_ids: list[str]
    impact_level: Literal["NONE", "LOW", "MEDIUM", "HIGH"]
    reasons: list[str]


class LiquidityImpact(BaseModel):
    status: Literal["OK", "CONSTRAINED", "UNKNOWN"]
    reasons: list[str]


class RiskBudgetImpact(BaseModel):
    status: Literal["WITHIN_BUDGET", "NEAR_LIMIT", "EXCEEDS_LIMIT", "UNKNOWN"]
    reasons: list[str]


class ConcentrationConflict(BaseModel):
    conflict_id: str
    exposure_type: str
    current_value: float | None
    projected_value: float | None
    threshold: float | None
    rule_id: str


class SuitabilityCondition(BaseModel):
    condition_id: str
    description: str
    verification_source: str


class SuitabilityAssessment(BaseModel):
    result: Literal[
        "SUITABLE",
        "CONDITIONALLY_SUITABLE",
        "CURRENTLY_NOT_SUITABLE",
        "INSUFFICIENT_INFORMATION",
    ]
    portfolio_impact: PortfolioImpact
    goal_impact: GoalImpact
    liquidity_impact: LiquidityImpact
    risk_budget_impact: RiskBudgetImpact
    concentration_conflicts: list[ConcentrationConflict]
    required_conditions: list[SuitabilityCondition]
    reasons: list[str]
    limitations: list[str]
```

### 10.4 v0 确定性规则

第一版优先使用可解释的确定性规则：

1. 缺少真实持仓，或持仓仅来自 `MOCK/UNAVAILABLE`，且问题要求个性化判断：`INSUFFICIENT_INFORMATION`；
2. 单一标的或同一行业超过配置阈值：至少 `CONDITIONALLY_SUITABLE`，严重时 `CURRENTLY_NOT_SUITABLE`；
3. 近期高流动性目标与高波动配置冲突：`CURRENTLY_NOT_SUITABLE`；
4. 风险画像缺失：不得输出无条件 `SUITABLE`；
5. 股票研究 `LIMITED`：适配性不能为 `SUITABLE`；
6. 股票研究质量较高不代表适配性自动通过。

阈值必须集中在 Policy 配置或代码常量中，有 Rule ID、有测试，不散落在 Prompt。

### 10.5 阶段验收场景

- 好资产 + 用户行业过度集中 → 不适合继续增加；
- 好资产 + 缺少持仓 → 信息不足；
- 研究结果 LIMITED → 不允许给出适合买入；
- 用户半年内有重大现金目标 → 高波动配置产生流动性冲突；
- 同样资产对不同用户产生不同适配性结果；
- 运行时 `mock-java` 示例持仓 → `INSUFFICIENT_INFORMATION`，不得触发真实用户集中度结论；
- 显式 `TEST_FIXTURE` 快照可以稳定触发行业集中度规则；
- 所有规则可解释并带 Rule ID。

---

## 11. 阶段 5：最小深层认知内核

### 11.1 目标

建立薄 Cognitive Kernel，让顶层处理“下一步行动”，而不是继续把所有逻辑加入旧 Root Graph。

建议新增：

```text
src/stockwise_analysis/cognitive/contracts.py
src/stockwise_analysis/cognitive/state.py
src/stockwise_analysis/cognitive/graph.py
src/stockwise_analysis/cognitive/nodes.py
src/stockwise_analysis/cognitive/action_policy.py
```

### 11.2 InputEvent

```python
class InputEvent(BaseModel):
    event_id: str
    event_type: Literal[
        "USER_MESSAGE",
        "USER_APPROVAL",
        "SCHEDULED_WAKEUP",
        "MARKET_EVENT",
        "ACCOUNT_CHANGED",
        "GOAL_DEADLINE",
        "TASK_RESUMED",
    ]
    authenticated_user_id: str
    occurred_at: datetime
    source: str
    payload: dict
    conversation_id: str | None = None
    task_id: str | None = None
```

首个切片只接收 `USER_MESSAGE`。其他类型完成 Schema 和拒绝/禁用逻辑，不必立即接入真实事件源。

### 11.3 CognitiveState v0

```python
class SituationModel(BaseModel):
    explicit_request: str | None
    speech_act: str
    inferred_purposes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    stakes: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class CognitiveUncertainty(BaseModel):
    uncertainty_id: str
    kind: Literal["FACTUAL", "INTENT", "PREFERENCE", "DATA", "MODEL", "ACTION_CONSEQUENCE"]
    description: str
    materiality: Literal["LOW", "MEDIUM", "HIGH"]
    resolution_strategy: Literal["ASK_USER", "RETRIEVE", "CALL_DOMAIN", "DISCLOSE_AND_CONTINUE"]


class CognitiveState(TypedDict, total=False):
    run_id: str
    conversation_id: str | None
    task_id: str | None
    authenticated_user_id: str
    input_event: dict

    situation: dict
    goals: list[dict]
    constraints: list[dict]
    uncertainties: list[dict]
    recalled_memories: list[dict]

    candidate_actions: list[dict]
    selected_action: dict | None
    domain_request: dict | None
    domain_outcome: dict | None

    final_response: dict | None
    status: str
    events: list[dict]
    errors: list[dict]
```

`CognitiveState` 中的字典字段仅用于 LangGraph Checkpointer 兼容，写入前必须通过 `SituationModel / GoalRef / DomainConstraint / CognitiveAction / DomainRequest / DomainOutcome` 等显式模型验证并 `model_dump()`。节点之间不得传播未验证的任意字典。

第一版不要求完整持久化 Belief 生命周期。先使用 `EvidenceFact / Finding / Uncertainty` 构建可验证链路。

### 11.4 Cognitive Graph v0

```text
START
→ ingest_event
→ load_context
→ understand_situation
→ infer_goals
→ assess_uncertainty
→ select_next_action
    ├─ RESPOND → compose → verify → END
    ├─ ASK_USER → interrupt → END/RESUME
    ├─ INVOKE_DOMAIN → Finance Runtime → assimilate → compose → verify → END
    └─ 其他动作 → Action Policy 返回 ACTION_NOT_ENABLED → 受限响应 → END
```

### 11.5 Action Policy

LLM 可以提出候选行动，最终动作必须由 Policy 校验：

- 是否在当前启用行动集合；
- 是否有权限；
- 是否超过预算；
- 是否缺少会实质改变结果的用户信息；
- 是否需要领域能力；
- 是否会产生持久化副作用；
- 是否违反只读边界。

### 11.6 阶段验收

- 稳定知识问题选择 `RESPOND`；
- 股票个性化问题选择 `INVOKE_DOMAIN`；
- 缺少必要用户选择时选择 `ASK_USER`；
- “条件合适时帮我看着”可以提出 `CREATE_TASK` 候选，但第一阶段 Policy 必须返回 `ACTION_NOT_ENABLED` 并清晰说明尚未建立观察任务；
- Policy 能拦截未启用行动；
- Cognitive Kernel 不直接调用 MCP；
- Finance Runtime 不直接向用户发送消息。

---

## 12. 阶段 6：CommunicationPlan 与 Response Verification

### 12.1 目标

替换“领域结果直接进入 Summary Model”的单层表达方式。

建议新增：

```text
src/stockwise_analysis/cognitive/communication.py
src/stockwise_analysis/cognitive/response_verifier.py
```

### 12.2 CommunicationPlan

```python
class CommunicationClaim(BaseModel):
    claim_id: str
    claim_type: Literal[
        "FACT",
        "ANALYSIS",
        "SUITABILITY",
        "LIMITATION",
        "NEXT_STEP",
    ]
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    required_disclosure_ids: list[str] = Field(default_factory=list)


class UserChoice(BaseModel):
    choice_id: str
    label: str
    consequence: str


class CommunicationPlan(BaseModel):
    communication_type: Literal["ANSWER", "QUESTION", "NOTIFICATION", "STATUS"]
    claims: list[CommunicationClaim]
    uncertainty_disclosures: list[str]
    user_choices: list[UserChoice]
    proposed_next_step: str | None
    tone: str
    detail_level: str
```

处理顺序必须是：

```text
DomainOutcome
→ CommunicationPlan（结构化 Claim + 证据引用）
→ Claim Verification
→ Natural Language Renderer
→ Response Guardrail
→ Final Response
```

自然语言 Renderer 只能改写表达，不得新增 Claim。Claim Verification 优先使用 ID 引用和确定性规则；无法确定性验证的自然语言主张必须标记给 Critic，不得假装已经完成事实校验。

### 12.3 Response Verification

至少检查：

1. 回复中的事实是否能映射到 EvidenceFact；
2. 是否将 INFERRED 写成 CONFIRMED；
3. 是否遗漏 `LIMITED/PARTIAL`；
4. 是否把资产质量写成用户适配性；
5. 是否与用户目标或风险约束冲突；
6. 是否提出系统不具备的写操作；
7. 是否包含承诺但没有创建 Task；
8. 是否使用伪精确可信度。

复核输出：

```python
class ResponseIssue(BaseModel):
    issue_code: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    claim_id: str | None = None
    reason: str


class ResponseReview(BaseModel):
    decision: Literal["PASS", "REVISE", "ASK_USER", "LIMITED", "BLOCK"]
    issues: list[ResponseIssue]
    audit_codes: list[str]
```

`ResponseIssue` 至少包含稳定 `issue_code`、严重度、关联 `claim_id` 和可公开修正理由，不得使用任意字典承载复核问题。

### 12.4 阶段验收

- 资产研究和用户适配性分段表达；
- 每个事实性和分析性 Claim 都有有效 evidence/finding 引用；
- 缺少持仓时不会说“适合你”；
- LIMITED 状态进入最终回复；
- LLM 失败时有确定性降级；
- 复核失败最多修订一次，避免无限循环。

---

## 13. 阶段 7：最小持续任务（第二阶段交付）

只有前述垂直切片稳定后才实施。

只有 TaskRepository、取消接口、去重键、唤醒条件和恢复测试全部完成后，Action Policy 才能正式启用 `CREATE_TASK / UPDATE_TASK / WAIT`。不得先启用动作、后补持久化。

### 13.1 FinancialTask

```python
class FinancialTask(BaseModel):
    task_id: str
    user_id: str
    task_type: Literal[
        "STOCK_MONITORING",
        "VALUATION_MONITORING",
        "PORTFOLIO_RISK_SCAN",
    ]
    objective: str
    status: Literal[
        "PLANNED",
        "RUNNING",
        "WAITING_USER",
        "SCHEDULED",
        "COMPLETED",
        "CANCELLED",
        "FAILED",
    ]
    trigger: dict
    next_wakeup_at: datetime | None
    notification_policy: dict
    created_at: datetime
    updated_at: datetime
```

### 13.2 首个任务场景

只实现一种真实场景：

```text
用户要求在估值或价格达到条件时重新评估股票
→ 询问/确认触发条件
→ CREATE_TASK
→ Scheduler 产生 SCHEDULED_WAKEUP
→ Cognitive Kernel 恢复
→ Finance Runtime 重新分析
→ 达到条件才产生 NOTIFY 建议
→ 未达到条件继续 WAIT，不打扰用户
```

### 13.3 限制

- Scheduler 只唤醒，不生成结论；
- 通知默认只是生成通知记录，不自动接第三方渠道；
- 任务必须可取消；
- 每次唤醒有预算和去重键；
- 任务不能执行交易。

---

## 14. Guardrails

实现四个独立时点，不合并成一个万能节点：

### 14.1 Plan Guardrail

- 目标是否明确；
- Skill 和 Capability 是否注册；
- 是否超过预算；
- 是否请求不允许的写能力；
- 是否重复执行已经成功且幂等的步骤。

### 14.2 Action Guardrail

- 当前行动是否启用；
- 用户权限是否满足；
- Capability 是否属于本轮候选集；
- 参数 Schema 是否有效；
- 是否满足只读边界。

### 14.3 Data-quality Guardrail

- Observation 是否吞错；
- 数据是否过期；
- 必需能力是否缺失；
- 来源是否冲突；
- 是否达到本分析类型完成标准。

### 14.4 Response Guardrail

- 是否编造；
- 是否隐藏限制；
- 是否把推断写成事实；
- 是否把股票质量等同于用户适配性；
- 是否提出无权限操作；
- 是否包含来源时间和适当风险说明。

Guardrail 的 `block/modify/ask_user` 结果必须记录审计码。

### 14.5 双路径安全覆盖

迁移期不得只描述新路径 Guardrails，而不核对旧默认路径的等价安全能力。阶段 0 建立并在每个阶段更新安全覆盖矩阵：

| 安全能力 | 旧 Root Graph | 新 Cognitive + Finance 路径 | 切换门槛 |
|---|---|---|---|
| 身份绑定与用户隔离 | 标出现有实现与缺口 | 必须完整实现 | 两条路径均无跨用户读取 |
| Plan 约束 | 标出现有等价机制 | 独立 Plan Guardrail | 新路径全量通过 |
| Action 白名单/只读 | 复用候选集、权限和预算检查 | 独立 Action Guardrail | 两条路径均拒绝越权和写金融操作 |
| Data-quality/coverage | 标出现有 Normalizer/Coverage | 独立 Data-quality Guardrail | 新路径不低于旧路径，mock 不得当 live |
| Response 事实与限制复核 | 标出现有校验与缺口 | 独立 Response Guardrail | 新路径事实引用和限制披露通过 |
| 审计事件 | 标出现有事件 | 统一审计码 | 可按 run_id 追踪 |

新路径在受控配置下必须完整执行四时点 Guardrails。旧路径在仍为默认期间不要求物理复制同一套节点，但必须保留身份、只读、工具白名单和数据质量等不可降低的安全能力。任何旧路径缺口必须记录 owner、影响、补偿控制和退役条件。

---

## 15. Tool 与 Skill 约束

必须保持以下链路：

```text
Financial Skill
→ Toolset
→ Unified Capability
→ Gateway Routing
→ Raw Tool
```

禁止：

- Cognitive Kernel 看到 51 个原始 MCP Tool；
- LLM 自行选择 MCP 服务和供应商；
- Skill 绕过 Gateway；
- Gateway 决定业务策略；
- Tool 返回原始字典直接进入最终回复。

建议 Toolset：

```text
market_read
fundamental_read
news_read
portfolio_read
financial_profile_read
planning_compute
```

Toolset 第一版可以建立在当前 `CapabilityRegistry` 之上，通过分组字段或独立 Registry 实现，但必须有唯一真源，不能维护两份互相漂移的清单。

`src/stockwise_analysis/skills/` 表示 Python 运行时 Financial Skill；仓库根目录 `skills/stock-analysis-skill/` 表示外部 `SKILL.md`/Node 资产。两者不能通过隐式 import 或同名动态加载混用，第一阶段外部 Skill 只作为迁移参考。

目录命名边界必须明确：

```text
domain/          = 现有纯确定性金融计算层，禁止依赖 LangGraph/LangChain/MCP/Mem0
domains/         = 新增领域编排和跨层契约层，可以依赖 Adapter/Registry/Graph
```

如团队认为单复数目录过于相似，可在阶段 0 决定将新增层统一命名为 `domain_runtime/`；一旦确定不得并存两种命名。

---

## 16. Memory、State、History 和 Task 边界

| 类型 | 作用 | 存储 |
|---|---|---|
| Cognitive State | 本次认知运行 | LangGraph Checkpointer |
| FinancialBusinessState | 本次金融领域执行 | 子图 State；需要恢复时使用独立 Checkpointer namespace |
| Conversation | 前端对话连续性 | Chat Session Store |
| User Financial Profile | 稳定结构化用户事实 | Java/结构化数据库 |
| Semantic Memory | 已确认稳定偏好召回 | Mem0 |
| Analysis/Decision History | 证据、结果和审计 | History Store |
| FinancialTask | 持续任务 | Task Repository |
| Commitment | 系统和用户未完成承诺 | Task/Commitment Store |

禁止把临时行情、原始 MCP 响应、未确认推断和一次性结论自动写入 Mem0。

证据与研究结果的跨会话追溯由 Analysis/Decision History 承担；Mem0 不作为 `EvidenceFact/Finding` 数据库，也不作为研究快照缓存。Checkpointer 只保证运行恢复，不自动等于长期业务历史。

---

## 17. API 兼容和切换策略

### 17.1 兼容原则

- 保持现有 `/api/v1` 请求响应兼容；
- 保持现有 SSE 事件可用；
- 保持 `thread_id / run_id` 语义；
- 保持恢复 API；
- 新内部契约不得直接暴露敏感用户数据。

### 17.2 切换原则

在新垂直切片验收前：

- 当前 Root Graph 继续作为默认路径；
- 新 Cognitive Graph 通过独立 Application 装配或受控配置启用；
- 不复制一套 MCP Gateway；
- 新旧路径共用 Capability Registry、Adapter、Normalizer 和 Domain Engine。

切换不是单一 feature flag 动作，必须通过以下门禁：

1. 安全覆盖矩阵已更新，身份、用户隔离、外部金融只读和 mock 隔离不存在 P0/P1 缺口；
2. 新路径四时点 Guardrails 全量启用并通过策略测试；
3. 同输入对照测试覆盖正常、PARTIAL/LIMITED、供应商失败、预算耗尽和用户数据不可用；
4. 新路径的 coverage、provenance、限制披露和错误可见性不低于旧路径；
5. Checkpoint namespace、History 幂等键和 fallback 边界经故障注入验证；
6. 完成灰度启用、观测指标、回滚条件和 owner 记录后，才可提高新路径流量；
7. 在新路径稳定前不得删除旧路径；删除旧路径必须另立任务并获得明确授权。

切换前必须完成同输入对照测试：

```text
旧路径结果
vs
新路径 FinancialDomainOutcome + Communication
```

新路径不得降低数据覆盖、来源保留和错误披露。

旧路径只允许在领域调用和任何内部写入发生前作为故障回退目标。一旦产生 `DomainRequest` 执行、Checkpoint/History/Task 写入或外部调用副作用，必须返回结构化失败并依幂等策略恢复，不得自动重跑旧路径。

---

## 18. 测试策略

### 18.1 契约测试

- DomainRequest/Outcome；
- FinancialDomainRequest/Outcome；
- StockResearchResult；
- SuitabilityAssessment；
- CognitiveAction；
- InputEvent。

### 18.2 Policy 测试

- 未启用行动被拒绝；
- 原始 Tool 名不能进入认知层；
- 非只读 Capability 被拒绝；
- 缺认证身份不能读取用户数据；
- LIMITED 研究不能得到 SUITABLE；
- 缺持仓不能伪造组合适配性；
- `mock-java/is_mock` 账户数据不能驱动真实个性化结论；
- 显式 `TEST_FIXTURE` 与运行时 `MOCK` 具有不同 Policy 结果；
- StockResearch confidence 只能由确定性策略产生。

### 18.3 Graph 测试

- direct response；
- ask user；
- invoke finance；
- finance result assimilate；
- response revise 一次；
- budget exhausted；
- interrupt/resume；
- 多轮 Observation 隔离；
- 领域调用前失败可以受控回退旧路径；
- 产生 DomainRequest 或内部写入后失败不得回退和重复执行；
- Finance Runtime 不触发旧 `compose_response / persist_memory / persist_history`；
- `MarketDataCoreGraph` 不读写 `workflow_plan/current_task_id`；
- 旧 Wrapper 和新 StockResearchGraph 复用同一核心拓扑；
- Cognitive Graph 与领域子图 Checkpoint namespace 隔离。

### 18.4 金融场景测试

至少覆盖：

1. “什么是市盈率？”
2. “600519 现在多少钱？”
3. “分析贵州茅台基本面。”
4. “结合我的持仓，茅台适合买吗？”
5. “我已经有很多白酒，还能继续买吗？”
6. “半年后要买房，现在适合提高股票仓位吗？”
7. “财报数据拿不到时还能得出什么结论？”
8. “条件合适时帮我看着。”

场景 8 的分阶段预期：阶段 5 返回 `ACTION_NOT_ENABLED` 且不得假装已建立任务；阶段 7 完成后才验收真实 `CREATE_TASK → WAIT → SCHEDULED_WAKEUP`。

### 18.5 回归要求

每个阶段至少执行：

```powershell
python -m compileall -q src
pytest -q
git diff --check
```

如项目提供更精确命令，以仓库实际配置为准。不得通过删除或弱化现有测试获得通过。

---

## 19. 可观测性

新增事件建议：

```text
cognition.event.ingested
cognition.goal.inferred
cognition.uncertainty.detected
cognition.action.selected
cognition.domain.requested
cognition.domain.completed
cognition.response.reviewed

finance.snapshot.loaded
finance.skill.selected
finance.stock_research.completed
finance.suitability.completed
finance.outcome.created

task.created
task.scheduled
task.woken
task.cancelled
```

事件必须包含公开理由和审计码，但不记录隐藏思维链、密钥、认证令牌或完整敏感账户数据。

---

## 20. 失败与降级

| 失败点 | 降级行为 |
|---|---|
| LLM 理解失败 | 规则版理解或 ASK_USER |
| Cognitive Graph 在任何领域调用和内部写入前不可用 | 可以回退当前 Root Graph 路径，并记录 fallback 审计事件 |
| Cognitive Graph 已产生 DomainRequest、Task、History 或其他内部写入后失败 | 禁止自动回退，返回结构化 FAILED/LIMITED，避免重复执行 |
| Finance Runtime 失败 | 返回结构化 FAILED/LIMITED |
| MCP 主源失败 | 按现有白名单切备用源 |
| 用户状态服务失败 | 客观研究可继续；个性化适配为信息不足 |
| Suitability 失败 | 返回客观研究，不生成个性化结论 |
| Response Model 失败 | 确定性模板降级 |
| Mem0 失败 | 无记忆继续 |
| Scheduler 失败 | 任务保持 SCHEDULED，记录错误，不丢任务 |
| 预算耗尽 | 返回 LIMITED + limitations |

任何降级不得伪造成功数据。

---

## 21. 安全与隐私

1. 用户身份必须来自认证会话；
2. 账户数据按目标最小化读取；
3. 不将完整账户数据传给不需要它的模型节点；
4. 日志和事件脱敏；
5. 不保存原始密钥和令牌；
6. 不将一个用户的 State、Memory、Task 暴露给另一个用户；
7. 所有持续任务可查看、取消和审计；
8. 第一阶段外部金融和账户操作只读；允许受控写入 Checkpoint、Conversation 和审计历史；
9. 所有个性化结论显示数据时间和限制；
10. 不承诺收益，不伪装专业持牌投顾。

---

## 22. 代码质量要求

- `domain/` 不 import LangGraph、LangChain、MCP 或 Mem0；
- Graph 节点保持单一职责；
- 外部依赖通过 Protocol/Adapter 注入；
- 所有 State 和跨层对象使用显式 Schema；
- 禁止跨层直接读取内部字段；
- 不复制 Capability 清单；
- 不使用魔法字符串散落定义行动和状态；
- Rule 必须有稳定 Rule ID；
- 错误必须结构化；
- 节点必须可单元测试；
- 新代码必须通过格式和静态基础检查；
- 保留已有用户修改，不重置脏工作区。

---

## 23. 交付物

每个阶段结束必须交付：

1. 实现代码；
2. 新增/更新测试；
3. 迁移矩阵状态更新；
4. 当前 Graph 拓扑图；
5. 新旧路径兼容说明；
6. 已知限制；
7. 测试结果；
8. 下一阶段建议。

最终交付报告格式：

```text
完成内容
- ...

架构边界
- Cognitive Kernel：...
- Finance Runtime：...
- Stock Research：...
- Suitability：...

兼容性
- API：...
- State/Checkpoint：...
- MCP/Java：...

验证结果
- compileall：...
- pytest：...
- diff check：...

未完成与限制
- ...

下一步
- ...
```

---

## 24. 阶段总验收门槛

首个端到端垂直切片完成的定义：

1. 用户输入首先进入 Cognitive Kernel；
2. Cognitive Kernel 能选择 `RESPOND / ASK_USER / INVOKE_DOMAIN`；
3. 个性化股票问题通过 `FinancialDomainRequest` 调用 Finance Runtime；
4. 股票数据仍通过统一 Capability 和 Gateway 获取；
5. 股票分析输出 `StockResearchResult`；
6. SuitabilityEngine 能结合真实或明确缺失的用户状态判断；
7. Finance Runtime 返回 `FinancialDomainOutcome`，不直接发送回复；
8. Cognitive Kernel 根据领域结果生成并复核回复；
9. 回复区分“资产质量”和“当前是否适合用户”；
10. 数据缺失、冲突和限制不会被隐藏；
11. 当前 API 和已有回归测试保持通过；
12. 全流程只读；
13. 不依赖 Hermes Runtime；
14. 不向 LLM 暴露全部原始 MCP Tools；
15. 全流程具有 run、domain request 和 evidence 可追踪性；第一阶段 `task_id` 允许为空，阶段 7 启用任务后必须全程可追踪。

未满足以上门槛时，不得宣布认知/金融分层已经完成。

---

## 25. 实施决策摘要

本 Prompt 最终确定：

1. 28/29 号作为目标架构；
2. 不一次性重建全部系统；
3. 不继续把旧 Root Graph 做成更大的单体；
4. 当前先建立 Cognitive ↔ Finance 契约边界；
5. 当前股票流程先抽取共享领域核心并保留兼容 Wrapper，不立即物理搬迁全部文件；
6. 第一条垂直切片是“股票客观研究 + 用户适配性”；
7. Belief 第一版先落到 EvidenceFact/Finding/Uncertainty，不建设完整持久化引擎；
8. Task/Scheduler 第二阶段只实现一个真实观察场景；
9. 所有金融计算保持确定性、可测试、可审计；
10. 第一阶段所有外部金融和账户操作只读；系统内部只允许受控写入运行状态、会话和审计记录；
11. 股票链先抽取不依赖 `RootState/workflow_plan` 的共享领域核心，再由旧 Wrapper 与新 StockResearchGraph 复用，不复制拓扑；
12. `build_stock_research_result` 在阶段 3 新建，不能在阶段 2 假设它已经存在；
13. 运行时 mock 账户数据永远不能冒充真实用户数据，集中度规则通过显式测试 Fixture 验证；
14. 跨会话研究证据进入 Analysis/Decision History，Mem0 只保存确认过的稳定偏好、目标和约束；
15. 新旧路径切换必须通过安全覆盖矩阵、对照测试、故障注入和灰度门禁。

开发过程中如发现当前代码事实与本文不一致，先记录证据并采用最小兼容调整，不得静默改变核心架构边界。
