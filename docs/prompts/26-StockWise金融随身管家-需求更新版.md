# StockWise 金融随身管家
# 需求文档（冻结基线版）

> 版本：v2.1
> 状态：当前需求基线（取代 v2.0，合并 27 号修改意见）
> 适用项目：`stockwise-analysis`
> 当前运行时：LangGraph
> 当前记忆层：Mem0
> 当前数据接入：MCP + Java Data API
> 当前分析能力：Python Analysis Capability
>
> 本 v2.1 是产品与架构需求的**唯一基线**。23 号文档（`23-全新股票分析系统-统一开发实施Prompt.md`）
> 在 v2.1 重写完成前，仅作为现有代码迁移参考；其与 v2.1 冲突的流程、字段和验收要求不再新增实现。
> 所有开发任务必须同时引用：v2.1 需求、迁移清单（§16）、对应验收测试（§19）。
>
> v2.1 相对 v2.0 的变更（合并 27 号修改意见）：
> - P0-1：声明唯一需求来源，禁止双文档并行指导；
> - P0-2：「意图分流」统一改称「执行模式选择」，避免误解为无边界；
> - P0-3：IntentRoute 契约补全 + 降级规则 + 名称解析边界定稿；
> - P0-4：冻结 Planner/Executor/TaskPlan/AgentAction 职责与重规划规则；
> - P0-5：Guardrails（策略判断）与 Tool Gateway（技术执行）职责分离，四时点校验；
> - P0-6：只读边界 + 用户身份不信任客户端；
> - P0-7：thread_id（持续对话）与 run_id（单次执行）拆分；
> - P1：QueryIntent 改造、记忆收窄、Analysis History 定义、宏观能力列外部依赖；
> - P2：LOAD_SKILL 暂不开放、DIRECT_RESPONSE 只答稳定知识、SSE schema、动态预算上限。
>
> 当前阶段不引入 Letta、Hermes、Phoenix 等新平台，只把现有 LangGraph + Mem0 + MCP + Java API 体系做完整。

---

## 0. 核心原则（不可变）

1. 没有股票代码不等于无法回答；
2. Agent 只能提出计划或动作，不能直接访问 MCP、Java API、数据库或 `domain/` 内部；
3. 工具调用、预算、权限、只读限制和恢复仍由外层运行时控制；
4. 指标、风险和回测等金融计算必须保持确定性、可复现；
5. Checkpointer、分析历史和长期记忆必须分开；
6. **当前版本仅提供只读分析、研究辅助和知识解释**，不下单、不调仓、不修改账户；
7. **用户身份与账户权限只能来自已认证会话/服务端令牌，不得直接信任请求体中的 user_id**。

---

## 1. 需求背景

StockWise 是面向金融领域的通用对话式智能管家（Financial Personal Assistant），不要求每个问题包含股票代码或归类为固定业务流程。合法输入示例：

```text
什么是市盈率？                              ← 知识问答，直接回答
600519 现在多少钱？                         ← 单点数据（已给代码），单能力查询
茅台现价？                                  ← 名称需解析，进 Agent Loop
美国非农数据对中国 A 股有什么影响？         ← 复杂研究，进 Agent Loop
我的持仓整体暴露在哪些风险上？              ← 持仓分析，进 Agent Loop
刚才提到的那只股票最近风险怎么样？          ← 上下文引用，进 Agent Loop
```

---

## 2. 核心架构决策：三层分层

```text
┌─────────────────────────────────────────────────────┐
│ 第一层：执行模式选择（轻量分类，非固定业务 route）   │
│   用户问题 → 判断：直接回答 / 单能力 / Agent Loop    │
│   拿不准时偏向 Agent Loop；快路径可升级              │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────┐
│ 第二层：Agent Loop（planner-executor-guardrails）    │
│   Planner  → 先产出动态 TaskPlan                    │
│   Executor → 选可执行步骤，产出 AgentAction          │
│   Guardrails → 四时点校验（计划/动作/数据/回答）     │
│   有界循环，重规划默认最多 2 次                      │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────┐
│ 第三层：确定性计算（domain/ 独立，零框架依赖）       │
│   统一能力 → Tool Gateway → Observation 标准化       │
│   → AnalysisInput → domain/ 分析 → AnalysisResult    │
└─────────────────────────────────────────────────────┘
```

执行模式选择**不是固定业务工作流分类**。它只决定本轮采用直接回答、单能力查询还是受控 Agent Loop；它不决定复杂研究的具体工具、分析步骤或最终结论。这样既避免旧式"问题必须命中预设类别"的限制，又避免被误解为"完全没有路由或边界"。

---

## 3. 第一层：执行模式选择

### 3.1 三个出口

| 出口 | 适用 | 执行 | 示例 |
|---|---|---|---|
| 直接回答 | 稳定知识解释 | LLM 单次调用，不调工具 | 什么是市盈率？ |
| 单能力查询 | 单点数据、单一事实，且标的已解析为 symbol | 一次统一能力调用 | 600519 现价？ |
| Agent Loop | 复杂研究、多实体、跨市场、名称需解析 | planner 规划 + executor 执行 | 非农对 A 股影响？ |

### 3.2 IntentRoute 契约（冻结）

```python
from typing import Literal
from pydantic import BaseModel, Field


class ToolProposal(BaseModel):
    capability: str
    arguments: dict[str, object] = Field(default_factory=dict)


class IntentRoute(BaseModel):
    mode: Literal["direct_response", "single_capability", "agent_loop"]
    reason: str
    confidence: float | None = None
    direct_answer: str | None = None      # direct_response 可带预览
    tool_proposal: ToolProposal | None = None  # single_capability 带建议工具
```

### 3.3 降级与升级规则（冻结）

1. `direct_response` 仅适用于**不依赖实时金融事实**的知识解释；涉及时点、价格、公告、政策、宏观数据、市场状态的内容，必须经数据能力或显式说明信息时效限制。
2. `single_capability` 的工具建议仍必须经过实体解析、参数校验和 Guardrails；它指"一次用户可见的统一能力调用"，内部主备路由由 Tool Gateway 完成。
3. **LLM 不可用、解析失败、置信度低或出现歧义时，默认进入 `agent_loop`**（宁可复杂不要漏）。
4. **快路径发现数据不足时必须升级到 `agent_loop`**，并记录升级事件。
5. 拿不准时偏向 `agent_loop`。

### 3.4 名称解析边界（定稿）

> "茅台现价"若未提供证券代码，由谁解析？定稿如下：

**采用方案 B：先执行 `market.resolve_instrument`，再执行行情能力。因此名称未解析的问题不属于 `single_capability`，走 `agent_loop`。**

理由：保持 `single_capability` "一次统一能力调用"的纯粹性；名称解析统一由 `resolve_instrument` 能力负责，不在各行情能力内部重复实现。仅当用户已提供 symbol（如 600519）时，`single_capability` 才直接调用行情能力。

```text
用户给 symbol（600519 现价）→ single_capability（quote）
用户给名称（茅台现价）      → agent_loop（planner: resolve → quote）
```

---

## 4. 第二层：Agent Loop

### 4.1 职责冻结表（不可重叠）

| 概念 | 唯一职责 | 不负责 |
|---|---|---|
| QueryIntent | 表达用户诉求、实体、时间范围、引用 | 选工具、决定中断 |
| IntentRoute | 选择本轮执行模式 | 生成复杂研究步骤 |
| TaskPlan | 定义目标、步骤、依赖、预算预估 | 执行工具 |
| Executor | 从计划中选一个可执行步骤，产出当前 AgentAction | 绕过 Guardrails |
| AgentAction | 某一轮的具体动作请求 | 改写整个计划 |
| Guardrails | 允许、拒绝、改写或要求补充（策略判断） | 执行工具、技术调用 |
| Tool Gateway | 调用外部统一能力并标准化 Observation（技术执行） | 决定业务策略 |

### 4.2 Planner 与 TaskPlan

Planner 接收 QueryIntent + 已解析实体 + 召回记忆，产出**动态 TaskPlan**（本次运行产物，非固定业务 route）。

```python
class TaskStep(BaseModel):
    step_id: str
    goal_id: str
    kind: Literal["call_tool", "load_skill", "analyze", "respond"]
    depends_on: list[str] = []
    input_ref: list[str] = []          # 引用前面步骤的产出
    expected_output: str | None = None
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    idempotency_key: str | None = None  # 重规划时不重复执行已成功且幂等的步骤


class TaskPlan(BaseModel):
    plan_id: str
    plan_version: int = 1
    goals: list[TaskGoal]
    steps: list[TaskStep]
    estimated_tool_calls: int
    depends_on: dict[str, list[str]] = {}
```

运行状态必须记录：

```text
plan_version、replan_count、max_replans（默认 2）、completed_step_ids、failed_step_ids
```

### 4.3 Executor 与 AgentAction

Executor 从计划中选下一个依赖已满足的步骤，产出 AgentAction：

```python
class AgentAction(BaseModel):
    action_type: Literal[
        "DIRECT_RESPONSE", "CALL_TOOL", "LOAD_SKILL",
        "ANALYZE", "ASK_USER", "REQUEST_CONFIRMATION",
        "REPLAN", "FINISH",
    ]
    reason: str
    tool_name: str | None = None
    tool_arguments: dict = {}
    skill_name: str | None = None
    question: str | None = None
    step_id: str | None = None  # 关联计划步骤
```

Executor 内部对**单个步骤的意外**（主源失败、字段缺失）可用局部有界 ReAct 自适应，但整体流程由 plan 驱动，不是扁平 ReAct。

### 4.4 重规划规则（冻结）

- 重规划只能**追加或替换尚未执行的步骤**，不能抹掉已获得的 Observation；
- 已成功且带 `idempotency_key` 的步骤不重复执行；
- 默认 `max_replans = 2`，超出后停止并输出当前可用结果（LIMITED）。

### 4.5 Guardrails（策略判断，一等公民）

Guardrails 是独立策略层，与 AgentAction 平级，**不与 Tool Gateway 重复**。

职责边界：

```text
Guardrails：策略判断
  - 是否允许该动作（白名单策略、只读/无副作用）
  - 是否超过预算（轮数/工具次数/时长/重规划次数）
  - 是否具备用户权限
  - 最终回答是否夸大、编造或伪装确定性

Tool Gateway：技术执行
  - 统一能力到原始工具的白名单技术映射
  - 参数 Schema 验证与转换
  - MCP/Java 调用、超时、重试、主备切换
  - 服务端吞错识别
  - Observation 标准化
```

校验结果统一为：

```python
class GuardrailResult(BaseModel):
    decision: Literal["allow", "block", "modify", "ask_user"]
    reasons: list[str] = Field(default_factory=list)
    replacement_action: AgentAction | None = None  # modify 时提供
    audit_code: str | None = None
```

**四时点校验**（不混为一个 check_output）：

```text
计划生成后：Plan Guardrail       （计划是否合理、工具是否在白名单、是否超预算）
工具调用前：Action Guardrail     （动作是否允许、权限、只读）
Observation 标准化后：Data-quality Guardrail  （数据是否可用、是否缺失关键字段）
最终回答生成后：Response Guardrail  （是否编造、是否伪装确定性、是否带来源时间）
```

---

## 5. 第三层：确定性计算

### 5.1 数据/分析分离

```text
统一能力 → Tool Gateway → Observation Normalizer → Observation
  → AnalysisInput → domain/ Python Analysis（零框架依赖）→ AnalysisResult
```

### 5.2 边界

- Agent 只编排，不进 domain/ 内部；
- domain/ 不 import LangGraph/LangChain/Mem0/MCP，纯确定性；
- MCP 返回原始数据，domain/ 负责计算；MCP 预计算指标最多作校验；
- 防未来函数：所有指标只依赖截至当前数据点。

### 5.3 Skill 定位

当前 Skill = Python Analysis Capability，只分析计算总结，**不查询数据**。

> **P2 收敛**：第一阶段不开放 `LOAD_SKILL` 动态加载外部 Skill，先将 Python Analysis Capability 作为受控确定性能力调用。普通分析优先确定性能力；需自然语言解释时才用模型节点。远程 Node Skill 暂不作依赖。

---

## 6. QueryIntent（P1-1，先于 Planner 改造）

```python
class IntentEntity(BaseModel):
    entity_id: str
    entity_type: Literal["instrument", "index", "sector", "industry",
                         "market", "portfolio", "macro", "news_topic",
                         "concept", "unknown"]
    raw_text: str
    normalized_value: str | None = None
    symbol: str | None = None
    resolution_status: Literal["unresolved", "resolved", "ambiguous"] = "unresolved"
    confidence: float | None = None


class ConversationReference(BaseModel):
    raw_reference: str           # "刚才那只"
    candidate_entity_ids: list[str] = []
    resolution_status: Literal["unresolved", "resolved", "ambiguous"] = "unresolved"


class QueryIntent(BaseModel):
    request_summary: str
    goals: list[IntentGoal] = []
    entities: list[IntentEntity] = []
    conversation_references: list[ConversationReference] = []
    time_range: TimeRange | None = None  # 含是否为推断值
    clarification_suggestion: str | None = None
    confidence: float | None = None
    # analysis_type 仅作旧流程 fallback，不再作强制中断/固定数据需求/预算唯一依据
    analysis_type: str | None = None
```

`check_missing_context` 语义改为：**是否存在无法合理默认且会明显改变答案的关键信息**，绝不等于"没有 symbol"。

---

## 7. 上下文与对话连续性（P0-7：thread vs run 拆分）

### 7.1 两个 ID

```text
thread_id：一段持续对话，保存会话消息、实体表和可恢复状态；
run_id：thread 中一次独立执行，记录事件、预算、计划和分析历史。
```

### 7.2 API 规则

```text
首次请求：服务端创建 thread_id + run_id；
后续对话：客户端传已存在且属于当前认证用户的 thread_id，服务端新建 run_id；
interrupt 恢复：使用原 thread_id 和原 run_id 的 checkpoint。
```

### 7.3 会话实体表

以 `thread_id` 为范围，候选实体必须带：来源消息、解析时间、置信度。指代消解（"刚才那只"）：
- 单候选 → 直接继续；
- 多候选 → 向用户提问消歧；
- 无候选 → 询问补充。

---

## 8. 中断与用户确认

### 8.1 不应中断

市场整体、宏观、跨市场、行业板块、指数、金融知识、可基于合理默认回答的问题、非关键字段缺失但仍可输出部分结果的问题——不得因缺股票代码中断。

### 8.2 可以中断

比较缺对象、股票名多候选无法消歧、"刚才那只"无对应实体、持仓分析权限不可用、时间范围影响重大且无法推断、执行交易或修改敏感信息、即将产生外部副作用且缺确认。

### 8.3 普通分析不要求保存确认

普通分析完成：Checkpointer 自动保存运行状态，记录 Analysis History，**不询问"是否保存"**，不自动写长期记忆。

> `REQUEST_CONFIRMATION` 当前版本仅为未来具有外部副作用的能力预留；遇到交易请求应返回"不支持执行交易，可提供分析建议"。

---

## 9. 记忆与状态（四类区分 + P1-2 收窄 + P1-3 Analysis History）

| 类型 | 作用 | 存储 |
|---|---|---|
| Conversation State | 当前对话和 Agent 状态 | LangGraph State |
| Checkpoint | 中断后恢复 | LangGraph Checkpointer |
| Analysis History | 历史分析记录和审计 | 持久化层（见 9.3） |
| Long-term Memory | 用户长期偏好和稳定事实 | Mem0 |

### 9.1 Mem0 读取

对话开始读：用户画像、风险偏好、投资目标、最近相关记忆。失败则无记忆继续，不阻断主流程。

### 9.2 Mem0 写入（P1-2 收窄）

只写：用户明确要求记住的稳定偏好、已确认的风险偏好和长期目标、明确稳定对后续对话有帮助的事实。

**不自动写**：临时行情、未确认推断、原始 MCP 响应、账户敏感信息、一次性结论。

### 9.3 Analysis History（P1-3 定义）

```text
history_id、thread_id、run_id、authenticated_user_id、
request_snapshot、intent_snapshot、plan_version、
observations_summary、analysis_result、
source_timestamps、status、created_at、retention_policy
```

明确：保存范围、查询权限（仅本人）、保留期限、脱敏策略、删除机制。

---

## 10. Observation 与数据质量

所有工具结果先转统一 Observation：

```text
observation_id  capability  status  data
source  source_tool  requested_at  data_time
quality  provenance  error  limitations
```

### 10.1 吞错识别

MCP 返回 `{"error": true, "message": "..."}` 即使协议层 isError=false，必须标准化为 `Observation.status = FAILED`。

### 10.2 数据状态

```text
SUCCESS  PARTIAL  FAILED  LIMITED  NOT_REQUIRED
```

模型必须据状态生成回答，不得隐藏数据缺失。

---

## 11. 运行预算与降级（P2-4 具体上限）

### 11.1 动态预算上限（冻结）

```text
执行模式选择模型调用：≤ 1 次
计划模型调用：≤ 2 次（含 1 次重规划）
单工具超时：20s（含云端 RTT）
单次 Java 工具超时：10s
最大工具调用数：按模式分档（direct=0 / single=1 / loop≤14）
最大重规划数：2
最大运行时长：240s（comprehensive 上限）
单次分析能力调用：60s
```

预算耗尽后返回固定格式：`status=LIMITED` + limitations 说明"因预算限制停止"。

### 11.2 降级

- 工具失败：重试或切备用（akshare-one source=xueqiu/sina）；
- 非关键缺失：PARTIAL 继续；
- 关键缺失：LIMITED；
- 全数据源失败：结构化失败；
- Mem0 失败：无记忆继续；
- 分析能力失败：已获取数据 + 失败说明；
- 超预算：停止，返回当前可用结果。

不得用 stock-wrapper 或旧接口作隐式备用源。

---

## 12. 统一能力与 Tool Gateway

```text
market.resolve_instrument        market.get_realtime_quote
market.get_historical_prices     market.get_financial_statements
market.get_valuation             market.get_industry_context
market.get_money_flow            market.get_news
portfolio.get_current_positions  portfolio.get_account_snapshot
portfolio.get_transaction_history user.get_risk_profile
```

> **P1-4 宏观能力列外部依赖**：`macro.get_indicator`、`macro.get_release_history` 的数据源、Schema、时效、降级未验证前，**不纳入第一阶段验收**。在 macro.* 验收完成前，"非农对 A 股影响"等场景不得承诺基于真实宏观数据完成，可用市场代理 + 明确说明数据限制。

Tool Gateway 负责技术执行（白名单映射、Schema、MCP/Java 调用、超时重试、主备切换、吞错识别、Observation 标准化）。

> **只读边界（P0-6）**：Tool Gateway 白名单中**不得出现**下单、撤单、调仓、资金划转、账户修改等写能力。

---

## 13. API 与事件流（P0-7 + P2-3）

### 13.1 请求

```json
{
  "thread_id": "已存在则传，首次省略由服务端创建",
  "user_id": "由认证令牌解析，不直接信任请求体",
  "message": "美国非农数据对中国A股有什么影响？",
  "metadata": {}
}
```

### 13.2 事件（P2-3 公共 schema）

事件需定义：公共 schema、排序规则、是否允许重复、错误码、脱敏规范。

```text
run.started  intent.routed  context.loaded  plan.created
guardrail.checked  agent.decided  tool.started  tool.completed
tool.failed  observation.created  skill.started  skill.completed
replan.triggered  upgrade.to_agent_loop  interrupt.required
response.delta  response.completed  run.completed  run.failed
```

> `response.delta` 在未实现真实 token 流之前**不得作为已交付能力**声明。

### 13.3 恢复

中断：Checkpointer 保存 → 发 `interrupt.required` → 返回需补充内容 → 同 thread_id + 原 run_id 用 `Command(resume=...)` 恢复 → 不重复已成功且幂等的步骤。

---

## 14. 关键验收场景

| 场景 | 输入 | 期望路径 |
|---|---|---|
| 知识问答 | 什么是市盈率？ | direct_response，不调工具，不要求股票代码 |
| 单点数据(已解析) | 600519 现价？ | single_capability，一次 quote |
| 名称需解析 | 茅台现价？ | agent_loop（planner: resolve → quote） |
| 单股分析 | 分析某股最近走势 | agent_loop，planner 规划取数+分析 |
| 市场整体 | 最近 A 股为什么波动大？ | agent_loop，不要求股票代码 |
| 跨市场 | 非农对 A 股影响？ | agent_loop，macro.* 未验收前用市场代理+说明限制 |
| 上下文引用 | 刚才那只股票风险怎样？ | thread 实体表消解，单候选直接继续 |
| 持仓分析 | 结合持仓分析风险 | Java portfolio，校验认证用户权限 |
| 高风险操作 | 帮我调仓 | 返回"不支持执行交易，可提供分析建议" |
| 工具错误 | MCP 返回 error:true | 吞错→FAILED→重试/降级，不伪装成功 |
| 兜底升级 | direct_response 发现需数据 | 升级 agent_loop，记录 upgrade 事件 |
| 无 LLM 降级 | LLM 不可用 | 安全降级到 agent_loop（规则版 planner） |

---

## 15. 目标流程（四时点 Guardrail 嵌入）

```text
START
  → 认证上下文 + 读取会话状态/记忆
  → QueryIntent 解析（实体、引用、时间范围）
  → 执行模式选择
      ├─ direct_response
      │    → Response Guardrail → END
      ├─ single_capability
      │    → Action Guardrail → Tool Gateway → Observation
      │    → Data-quality Guardrail → Response Guardrail → END
      └─ agent_loop
           → Planner → Plan Guardrail
           → Executor 选下一步 → Action Guardrail
           → Tool Gateway / 确定性 Analysis Capability
           → Observation → Data-quality Guardrail
           → 继续 / 局部重试 / 重规划（≤2次）/ 总结
           → Response Guardrail → END
```

所有外部数据路径：`统一能力 → Tool Gateway → Observation Normalizer → Observation`
所有确定性分析：`Observation → AnalysisInput → domain/ → AnalysisResult`

---

## 16. 与现有代码的迁移清单

| 当前模块/行为 | v2.1 目标 | 迁移处理 |
|---|---|---|
| `check_missing_context` 强制 symbol | 按真实歧义和风险决定补问 | 重写 |
| `build_data_requirements` 按 analysis_type 固定 | Planner 动态生成 TaskPlan | 保留为无 LLM fallback，逐步替换 |
| `dispatch_workflow` 消费固定 WorkflowPlan | 通用 Executor 消费动态步骤 | 重构（复用 WorkflowPlan 结构） |
| `select_action` 仅市场取数 | 有界通用步骤执行器 | 扩展，Agent 不直接执行工具 |
| 节点/Gateway 分散校验 | 独立 Guardrails 策略层 | 抽取策略，保留 Gateway 技术校验 |
| `RootState` 无会话实体表 | 支持引用消解 | 新增实体表、plan_version、运行计数 |
| `persist_memory` 自动沉淀摘要 | 只写稳定/明确/确认后记忆 | 收窄 |
| `confirm_user` 询问是否保存 | 普通分析直接结束 | 删除；仅留未来副作用确认 |
| API 用 run_id 充当 thread_id | 长对话与单次运行分离 | API + Checkpointer 重构 |
| `routing_policy` 仅 market.* | 支持宏观/跨市场 | 先验证新增 macro.*，后开放验收 |
| user_id 直接用请求体 | 认证令牌解析 | 认证中间件 |
| 无 Analysis History 持久化 | 历史记录层 | 新增（见 9.3） |

---

## 17. 开发实施顺序

### 阶段一：执行模式选择 + 语义修正（低风险高价值）
- 新增执行模式选择节点（STRUCTURED_LLM，三 mode 输出 + 降级/升级）；
- 删除"缺股票代码统一中断"、"普通分析统一询问保存"；
- 加 direct_response 快路径 + 兜底升级；
- 名称解析边界按 §3.4 定稿（名称→agent_loop）；
- 保留固定 WorkflowPlan 作 fallback。

### 阶段二：planner-executor + Guardrails
- WorkflowPlan 升级为 planner 动态生成 TaskPlan（含 step_id/idempotency_key）；
- select_action 扩展为通用 executor；
- 抽 `guardrails/` 独立策略层（四时点：Plan/Action/Data-quality/Response）；
- Guardrails 与 Tool Gateway 职责分离；
- 重规划机制（≤2 次，不抹已得 Observation）。

### 阶段三：上下文与记忆
- thread_id/run_id 拆分（API + Checkpointer）；
- state 新增会话实体表 + 指代消解；
- Mem0 写入收窄；
- Analysis History 持久化层；
- 认证中间件（user_id 不信任请求体）。

### 阶段四：复杂研究 + 宏观能力
- macro.* 验证接入（外部依赖，验收前不承诺场景）；
- planner 多步计划 + executor 局部 ReAct；
- 动态预算跟踪器（按 §11.1 上限）；
- 部分缺失与多工具失败处理。

### 阶段五：回归验收
- 现有测试全绿；
- 新增对话场景测试（无股票代码/多实体/上下文引用/工具错误/预算耗尽/Checkpointer 恢复/普通回答不写长期记忆/Guardrail 审计事件）。

---

## 18. 阶段验收门槛（可测）

### 阶段一完成条件
1. "什么是市盈率"不调工具、不要求股票代码；
2. "600519 现价"符合 single_capability 语义（已解析 symbol）；
3. "茅台现价"走 agent_loop（名称先 resolve）；
4. "最近 A 股为什么波动大"不因缺 symbol 中断；
5. 快路径发现缺实时数据能升级 Agent Loop；
6. 无 LLM 或分流输出非法时安全降级到 Agent Loop；
7. 普通分析不弹"是否保存"；
8. 普通分析不自动写长期记忆。

### 阶段二完成条件
1. 任一工具动作调用前可输出 Guardrail 审计事件；
2. 非白名单、写操作、无权限、预算耗尽动作不可到达 Gateway；
3. 重规划不重复执行已成功且幂等的步骤；
4. Tool Gateway 失败统一转为 FAILED 或 LIMITED Observation；
5. Agent/Graph/Gateway/domain 职责边界有独立单元测试；
6. 四时点 Guardrail 各自有测试。

### 阶段三及以后完成条件
1. 相同 thread_id 的上下文引用可正确消解；
2. 用户无法访问他人会话、持仓或分析历史（认证隔离）；
3. 宏观场景仅在真实 macro.* 验收后开放；
4. 所有最终回答显式反映数据时间、来源、缺失和限制。

---

## 19. 工程约束（必须遵守）

1. Agent 不得直接访问数据库或 MCP 原始客户端。
2. MCP 必须经 Tool Gateway 接入；Java 数据经 Java API。
3. **Guardrails 是一等公民**：所有 AgentAction/TaskPlan/最终回答显式过对应时点校验，策略不散落到节点。
4. **Guardrails（策略）与 Tool Gateway（技术）职责分离，不重复**。
5. Skill/Analysis Capability 不查询数据，不依赖 LangGraph/LangChain/Mem0/MCP。
6. QueryIntent 不直接决定工具，不直接触发 interrupt。
7. 没有股票代码不代表无法分析。
8. 普通分析不要求用户确认保存。
9. 所有工具结果先标准化为 Observation；业务错误不得当正常响应。
10. ReAct 必须有界；planner-executor 优于扁平 ReAct；重规划≤2 次。
11. Checkpointer / Analysis History / Long-term Memory / Conversation State 四类严格区分。
12. 数据不足必须显式返回限制，不编造。
13. 执行模式选择拿不准偏向 agent_loop；快路径可升级。
14. **当前版本只读，白名单禁写能力；user_id 不信任请求体，必须认证令牌解析**。
15. thread_id（持续对话）与 run_id（单次执行）分离。
16. 第一阶段不开放 LOAD_SKILL；DIRECT_RESPONSE 只答稳定知识。
17. 当前阶段不引入 Letta/Hermes/Phoenix 等新平台。
18. 确定性计算（domain/）零框架依赖，Agent 碰不到内部。

---

## 20. Letta 迁移边界

Letta 不属当前范围，但代码保留迁移可能。迁移时可替换：LangGraph Runtime、Mem0 Provider、对话状态管理。迁移必须保持稳定：MCP Tool 契约、Java API 契约、Observation 契约、AnalysisInput/AnalysisResult 契约、Skill 契约、权限约束、Guardrails 规则、高风险确认规则。

因此当前开发不得把业务数据结构、工具实现、记忆存储、分析能力、权限判断、Guardrails 规则写死到 LangGraph 节点内部——通过抽象接口隔离，让 runtime 可替换、Guardrails 可复用。

---

## 21. 当前交付标准

完成后系统应能：

```text
用户自然语言提问
  → 执行模式选择（direct_response / single_capability / agent_loop）
  → agent_loop 内 planner 规划 + executor 执行 + 四时点 guardrails 校验
  → 工具经 Gateway 执行，结果标准化为 Observation
  → 确定性计算完成分析
  → 模型生成最终回答（带来源时间、限制说明）
  → 普通分析直接结束
```

必须能处理：单股、多股、市场行业、宏观（macro.* 验收后）、跨市场、持仓、知识问答、连续上下文、数据不完整与工具失败。

交付重点不是增加更多固定 route，而是证明 Agent 能在金融领域内**分层可控地**动态选择行动：简单问题快、复杂问题稳、全程有校验、数据不编造、权限不越界、会话可延续。
