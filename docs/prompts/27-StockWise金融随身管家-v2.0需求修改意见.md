# StockWise 金融随身管家 v2.0
# 需求修改意见

> 审查对象：`26-StockWise金融随身管家-需求更新版.md`
>
> 结论：**建议采纳其总体方向，但在进入大规模重构前，必须补齐本意见中的 P0 定义。**
>
> 本文不是新的开发 Prompt；它用于把 v2.0 从“正确的架构愿景”补充为可实施、可测试、可复核的需求基线。

---

## 1. 总体判断

v2.0 的核心方向正确，应取代“按单只股票 + `analysis_type` 固定工作流”的产品边界：

```text
金融自然语言问题
  → 执行模式选择
  → 简单问题走快路径 / 复杂问题进入受控 Agent Loop
  → 外部数据统一为 Observation
  → 确定性 Python 分析
  → 可解释的最终回答
```

尤其应保留以下原则：

1. 没有股票代码不等于无法回答；
2. Agent 只能提出计划或动作，不能直接访问 MCP、Java API、数据库或 `domain/` 内部；
3. 工具调用、预算、权限、只读限制和恢复仍由外层运行时控制；
4. 指标、风险和回测等金融计算必须保持确定性、可复现；
5. Checkpointer、分析历史和长期记忆必须分开；
6. 当前系统仅做分析与研究辅助，不提供下单、调仓或账户修改能力。

但 v2.0 中仍有若干概念未冻结，直接编码会造成新的“节点、Agent、计划和校验层职责重叠”。以下修改项应先写入需求文档。

---

## 2. P0：开发前必须修改或明确的事项

### P0-1：明确唯一需求来源与文档优先级

### 问题

v2.0 一方面声明自己是“当前需求基线”，另一方面又声明不修改主开发文档 `23-全新股票分析系统-统一开发实施Prompt.md`，只在冲突时以自身为准。两个文档同时指导开发，会导致实现人员无法判断：旧流程是保留、迁移还是删除。

### 修改意见

在 v2.0 顶部增加明确规则：

```text
本 v2.0 是产品与架构需求的唯一基线。
23 号文档在 v2.1 重写完成前，仅作为现有代码迁移参考；
其与 v2.0 冲突的流程、字段和验收要求不再新增实现。
所有开发任务必须同时引用：v2.0 需求、迁移清单、对应验收测试。
```

并在后续开发前补一份“v2.0 → 23 号文档”的逐项迁移矩阵，禁止仅靠“冲突时以本文为准”的口头判断。

---

### P0-2：将“意图分流”改称为“执行模式选择”

### 问题

v2.0 表述“意图分流不是固定 route”，但它实际定义了三个固定出口：`direct_response`、`single_tool`、`agent_loop`。它不是旧式的业务工作流分类，但仍然是一个执行路径选择。

### 修改意见

统一使用如下表述：

```text
执行模式选择不是固定业务工作流分类。
它只决定本轮采用直接回答、单能力查询还是受控 Agent Loop；
它不决定复杂研究的具体工具、分析步骤或最终结论。
```

这样可避免把“非固定业务流程”误解成“完全没有路由或边界”。

---

### P0-3：补全 IntentRoute 契约和降级规则

### 问题

文档要求 `single_tool` 携带工具名和参数、`direct_response` 可带回答预览，但 `IntentRoute` 模型只有 `route` 和 `reason` 两个字段。同时没有规定 LLM 不可用、输出非法或置信度低时的行为。

### 修改意见

替换为明确契约：

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
    direct_answer: str | None = None
    tool_proposal: ToolProposal | None = None
```

同时写明：

1. `direct_response` 仅适用于不依赖实时金融事实的知识解释；
2. `single_capability` 的工具建议仍必须经过实体解析、参数校验和 Guardrails；
3. LLM 不可用、解析失败、置信度低或出现歧义时，默认进入 `agent_loop`；
4. 快路径发现数据不足时必须升级到 `agent_loop`，并记录升级事件；
5. `single_capability` 指“一次用户可见的统一能力调用”，其内部的主备路由由 Tool Gateway 完成。

### 必须回答的边界问题

“茅台现价”若未提供证券代码，究竟由谁解析？必须二选一：

```text
A. market.get_realtime_quote 统一能力内部负责解析名称；
B. 先执行 market.resolve_instrument，再执行行情能力，因此该问题不属于单能力快路径。
```

在这一点未定稿前，不得实现 `single_capability`。

---

### P0-4：冻结 Planner、Executor、TaskPlan 与 AgentAction 的职责

### 问题

文档同时定义了有步骤的 `TaskPlan` 和逐轮输出的 `AgentAction`，但没有说明二者谁拥有执行状态、重规划如何保留已完成结果、何时允许偏离计划。

### 修改意见

固定以下职责：

| 概念 | 唯一职责 | 不负责 |
|---|---|---|
| QueryIntent | 表达用户诉求、实体和时间范围 | 选工具、决定中断 |
| IntentRoute | 选择本轮执行模式 | 生成复杂研究步骤 |
| TaskPlan | 定义目标、步骤、依赖、预算预估 | 执行工具 |
| Executor | 从计划中选一个可执行步骤，并产出当前 AgentAction | 绕过 Guardrails |
| AgentAction | 某一轮的具体动作请求 | 改写整个计划 |
| Guardrails | 允许、拒绝、改写或要求补充 | 执行工具 |
| Tool Gateway | 调用外部统一能力并标准化 Observation | 决定业务策略 |

`TaskStep` 至少应有：

```text
step_id、goal_id、kind、depends_on、input_ref、expected_output、status、idempotency_key
```

运行状态还必须记录：

```text
plan_version、replan_count、max_replans、completed_step_ids、failed_step_ids
```

并明确：重规划只能追加、替换尚未执行的步骤，不能抹掉已获得的 Observation；默认最多重规划 2 次。

---

### P0-5：重构 Guardrails 契约，避免与 Gateway 重复

### 问题

当前文档同时要求 Guardrails 和 Tool Gateway 做白名单、参数校验、权限、超时和输出检查，职责存在重叠。示例 `Guardrail(Protocol)` 还会因方法体没有 `...` 而被 Pylance 识别为隐式返回 `None`。

### 修改意见

职责边界应为：

```text
Guardrails：策略判断
  - 是否允许该动作
  - 是否超过预算
  - 是否具备用户权限
  - 是否违反只读/无副作用边界
  - 最终回答是否夸大、编造或伪装确定性

Tool Gateway：技术执行
  - 统一能力白名单的技术映射
  - 参数 Schema 验证与转换
  - MCP/Java 调用、超时、重试、主备切换
  - 服务端吞错识别
  - Observation 标准化
```

校验结果建议统一为：

```python
class GuardrailResult(BaseModel):
    decision: Literal["allow", "block", "modify", "ask_user"]
    reasons: list[str] = Field(default_factory=list)
    replacement_action: AgentAction | None = None
    audit_code: str | None = None
```

并将校验拆为四个时点：

```text
计划生成后：Plan Guardrail
工具调用前：Action Guardrail
Observation 标准化后：Data-quality Guardrail
最终回答生成后：Response Guardrail
```

不要把“Observation 数据质量检查”和“自然语言回答合规检查”混为一个 `check_output()`。

---

### P0-6：明确只读分析边界和用户身份信任边界

### 问题

文档提到高风险操作与确认，但当前产品范围是不下单、不调仓、不修改账户。并且持仓权限不能信任客户端请求中传入的 `user_id`。

### 修改意见

写入不可变约束：

```text
当前版本仅提供只读分析、研究辅助和知识解释。
Tool Gateway 白名单中不得出现下单、撤单、调仓、资金划转、账户修改等写能力。
用户身份与账户权限只能来自已认证会话/服务端令牌，不得直接信任请求体中的 user_id。
```

因此 `REQUEST_CONFIRMATION` 仅为未来具有外部副作用的能力预留；当前版本遇到交易请求应返回“不支持执行交易，可提供分析建议”。

---

### P0-7：拆分 conversation thread 与一次 run

### 问题

v2.0 要求连续对话和“刚才那只”的指代消解，但当前 API 每次创建新 `run_id`，并将其同时用作 LangGraph `thread_id`。这只能恢复一次被 interrupt 的运行，不能支撑持续会话。

### 修改意见

定义两个 ID：

```text
thread_id：一段持续对话，保存会话消息、实体表和可恢复状态；
run_id：thread 中一次独立执行，记录事件、预算、计划和分析历史。
```

API 规则：

```text
首次请求：服务端创建 thread_id + run_id；
后续对话：客户端传已存在且属于当前认证用户的 thread_id，服务端新建 run_id；
interrupt 恢复：使用原 thread_id 和原 run_id 的 checkpoint；
```

实体表应以 `thread_id` 为范围，且候选实体必须带来源消息、解析时间和置信度。

---

## 3. P1：第一、二阶段必须补充的事项

### P1-1：QueryIntent 改造应先于 Planner

新的 QueryIntent 必须支持多实体、时间范围、引用和未解析实体。`analysis_type` 只能作为旧流程 fallback，不能再作为强制中断、固定数据需求或预算的唯一依据。

建议增加：

```text
entities[]：entity_id、entity_type、raw_text、normalized_value、resolution_status、confidence
conversation_references[]：原始指代、候选实体 ID、消歧状态
time_range：绝对/相对时间范围及是否为推断值
```

`check_missing_context` 的语义应改为“是否存在无法合理默认且会明显改变答案的关键信息”，绝不能等同于“没有 symbol”。

### P1-2：收窄长期记忆写入

现有实现会在每轮结束时写入“用户问题 + 分析结论”。v2.0 应改为只写：

```text
用户明确要求记住的稳定偏好；
已确认的风险偏好和长期目标；
明确、稳定、对后续对话有帮助的事实。
```

临时行情、未确认推断、原始 MCP 响应、账户敏感信息、一次性结论不得自动写入 Mem0。

### P1-3：定义 Analysis History

“新增持久化层”不足以开发。至少定义：

```text
history_id、thread_id、run_id、authenticated_user_id、request_snapshot、
intent_snapshot、plan_version、observations_summary、analysis_result、
source_timestamps、status、created_at、retention_policy
```

并明确保存范围、查询权限、保留期限、脱敏策略和删除机制。

### P1-4：将宏观能力列为外部依赖，不纳入第一阶段验收

当前统一能力只有 `market.*`，没有 `macro.*`。在 `macro.get_indicator`、`macro.get_release_history` 的数据源、Schema、时效性和降级策略完成验证前，不得承诺“非农对 A 股影响”场景可基于真实宏观数据完成。

---

## 4. P2：建议收敛以避免过早扩张

1. 当前没有成熟的通用 Skill 运行机制时，不要在第一阶段开放 `LOAD_SKILL` 动作；先将 Python Analysis Capability 作为受控的确定性能力调用。
2. `DIRECT_RESPONSE` 只能回答稳定知识。涉及时点、价格、公告、政策、宏观数据、市场状态的内容，必须经数据能力或显式说明信息时效限制。
3. SSE 事件需定义公共 schema、排序规则、是否允许重复、错误码和脱敏规范；`response.delta` 在未实现真实 token 流之前不得作为已交付能力。
4. 动态预算需要具体上限：路由模型调用数、计划模型调用数、最大工具调用数、单工具超时、最大重规划数、最大运行时长；预算耗尽后的固定响应格式也应定义。

---

## 5. 与当前代码的迁移清单

| 当前模块/行为 | v2.0 目标 | 迁移处理 |
|---|---|---|
| `query_graph.check_missing_context` 强制 `symbol` | 按真实歧义和风险决定是否补问 | 重写 |
| `build_data_requirements` 按 `analysis_type` 固定产出 | Planner 动态生成 TaskPlan | 保留为无 LLM fallback，逐步替换 |
| `dispatch_workflow` 消费固定 WorkflowPlan | 通用 Executor 消费动态步骤 | 重构 |
| `market_data_graph.select_action` 仅处理市场取数 | 有界的通用步骤执行器 | 扩展，不能让 Agent 直接执行工具 |
| 节点、Gateway 中分散校验 | 独立 Guardrails 政策层 | 抽取策略，保留 Gateway 技术校验 |
| `RootState` 无会话实体表 | 支持引用消解 | 新增实体表、计划版本、运行计数 |
| `persist_memory` 自动沉淀分析摘要 | 只写稳定、明确或确认后的记忆 | 收窄 |
| `confirm_user` 询问是否保存 | 普通分析直接结束 | 删除该流程；仅保留未来副作用确认机制 |
| API 用 run_id 充当 thread_id | 长对话与单次运行分离 | API 和 Checkpointer 配置重构 |
| `routing_policy` 仅有 `market.*` | 支持宏观/跨市场 | 先验证并新增 `macro.*`，后开放验收场景 |

---

## 6. 推荐的目标流程

```text
START
  → 认证上下文 + 读取会话状态/记忆
  → QueryIntent 解析（实体、引用、时间范围）
  → 执行模式选择
      ├─ direct_response
      │    → Response Guardrail → END
      ├─ single_capability
      │    → Action Guardrail → Tool Gateway → Observation
      │    → Response Guardrail → END
      └─ agent_loop
           → Planner → Plan Guardrail
           → Executor 选择下一步 → Action Guardrail
           → Tool Gateway / Deterministic Analysis Capability
           → Observation / Data-quality Guardrail
           → 继续、局部重试、重规划或总结
           → Response Guardrail → END
```

所有外部数据路径都必须经过：

```text
统一能力 → Tool Gateway → Observation Normalizer → Observation
```

所有确定性分析都必须经过：

```text
Observation → AnalysisInput → domain/ 或 Analysis Capability → AnalysisResult
```

---

## 7. 修改后的阶段验收门槛

### 阶段一完成条件

1. “什么是市盈率”不调用工具、不要求股票代码；
2. “茅台现价”符合冻结后的单能力语义；
3. “最近 A 股为什么波动大”不会因缺 `symbol` 中断；
4. 快路径发现缺实时数据时能升级 Agent Loop；
5. 无 LLM 或分流输出非法时，能安全降级到 Agent Loop；
6. 普通分析不弹出“是否保存”；
7. 普通分析不自动写入长期记忆。

### 阶段二完成条件

1. 任一工具动作在调用前都可输出 Guardrail 审计事件；
2. 非白名单、写操作、无权限和预算耗尽动作均不可到达 Gateway；
3. 重规划不重复执行已成功且具有幂等键的步骤；
4. Tool Gateway 失败统一转为 `FAILED` 或 `LIMITED` Observation；
5. Agent、Graph、Gateway 和 domain 的职责边界有独立单元测试。

### 阶段三及以后完成条件

1. 相同 `thread_id` 的上下文引用可被正确消解；
2. 用户无法访问他人会话、持仓或分析历史；
3. 宏观场景仅在真实 `macro.*` 能力验收后开放；
4. 所有最终回答显式反映数据时间、来源、缺失和限制。

---

## 8. 最终建议

在下一步开发前，不应直接把现有固定 Graph 改造成“完全自由的 Agent”。应先完成 P0 的契约冻结，再按“语义纠偏 → 执行模式选择 → Planner/Executor/Guardrails → 会话与宏观能力”推进。

这样既保留 v2.0 希望获得的灵活金融对话能力，也能保持金融分析系统最关键的可控性、可审计性、可恢复性与不编造原则。
