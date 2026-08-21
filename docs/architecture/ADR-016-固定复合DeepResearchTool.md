# ADR-016：固定复合 Deep Research Capability

> 状态：APPROVED
> 修订日期：2026-08-17
> 适用阶段：开发阶段，目标态直接生效

## 1. 决策

提供稳定公开 Capability ID：

```text
research.deep_search
```

它是 Runtime 内部的固定复合只读能力，不是新的 Domain、Skill、独立 Agent 服务或第二套搜索平台。它通过多轮拆题、原子检索、证据去重、压缩和确定性收口，返回一个结构化 `ResearchBundle` Observation。

`research.web_search` 继续表示单轮浅搜索；两个 ID 语义独立。不得用一个 ID 根据参数或开关承载两种输出契约。

## 2. 固定边界

- Deep Research 只能经 Capability Gateway 调用。
- Agent 只有在 `research.deep_search ∈ allowed` 时才能选择它。
- Feature Flag、entitlement、预算、只读和 Gateway 校验同时生效。
- Deep Research 内部只能调用原子搜索端口，不能递归调用 Capability Gateway 或另一个 Agent。
- 所有外部检索结果均为不可信内容，必须经过标准化、引用和提示注入防护。
- Deep Research 不访问账户写接口，不下单、不调仓、不转账。

## 3. 调用策略

默认优先使用 `research.web_search`。只有满足以下任一条件，并且 Deep 能力已经进入 `allowed`，Agent 才可选择 `research.deep_search`：

- 任务需要多个独立子问题；
- 需要跨来源核验冲突；
- 需要形成带证据的综合研究结论；
- Goal Coverage 明确要求浅搜无法提供的覆盖深度。

以下情况禁止调用 Deep：

- 简单事实或单一当前值查询；
- 已有 Observation 足以覆盖 Goal；
- 预算不足；
- Feature Flag 关闭；
- Capability 不在 `allowed`；
- 请求包含写账户、交易或绕过安全规则。

用户原句中的“深入”“全面”等词只能作为任务复杂度线索，不能发放权限。

## 4. 输入契约

```text
DeepResearchRequest
  request_id
  run_id
  user_id?
  question
  objective
  constraints[]
  known_observations[]
  budget
  deadline
```

要求：

- `question` 和 `objective` 必填；
- `budget` 由 Runtime 下发，调用方不能自行扩大；
- 已有 Observation 只作为已知证据，不把原始网页或供应商响应直接交给模型；
- 幂等键由 `request_id + objective + constraints + evidence_refs` 的稳定摘要产生，不包含已删除的 `analysis_type`。

## 5. 输出契约

```text
ResearchBundle
  status                # COMPLETE | PARTIAL | LIMITED | FAILED
  objective
  summary
  findings[]
  conflicts[]
  evidence[]
  coverage
  limitations[]
  provenance
  metrics
```

每条 Finding 必须引用一个或多个 Evidence。Evidence 至少包含来源 URI、标题、抓取时间、内容摘要、来源类型和质量标记。

状态规则：

- `COMPLETE`：关键 success criteria 均有有效 Evidence 覆盖；
- `PARTIAL`：已有可用证据，但至少一个关键 criteria 未覆盖；
- `LIMITED`：预算、Provider 或内容质量限制导致只能给有限结果；
- `FAILED`：没有可用证据或发生不可恢复错误。

不得把无引用的模型总结包装为 `COMPLETE`。

## 6. 内部工作流

```text
validate request
  → decompose objective
  → build bounded query plan
  → atomic search
  → normalize and deduplicate evidence
  → detect conflicts and gaps
  → optional bounded follow-up search
  → compress evidence
  → deterministic coverage check
  → assemble ResearchBundle
```

控制器拥有预算和停止权。模型可以建议子问题或结束，但不能修改预算、跳过 Guardrail 或自行宣称完成。

## 7. 原子搜索端口

Deep Research 依赖内部 `AtomicSearchPort`：

```text
search(query, *, limit, deadline, request_context) -> SearchPage
```

端口要求：

- 统一超时、重试、限流和熔断；
- 统一供应商错误为稳定错误码；
- 返回标准化来源和抓取时间；
- 不暴露凭证、内部 URL 或供应商原始响应；
- 不调用 `research.deep_search`，避免递归。

Provider 路由属于 Adapter 层。Deep Research 图不知道具体供应商名称。

## 8. 预算和停止

预算至少包含：

```text
max_rounds
max_queries
max_documents
max_total_chars
max_model_calls
timeout_seconds
```

任一上限到达后停止新增检索并按现有证据组装 `PARTIAL` 或 `LIMITED`。不得因为追求 `COMPLETE` 无限重试。

双层完成判断：

1. 模型判断是否还有值得检索的缺口；
2. 控制器根据 success criteria、Evidence 引用、冲突和预算作最终决定。

## 9. Registry 与装配

`research.deep_search` 只在 PostgreSQL Registry 登记一次：

- adapter：`local`
- read_only：`true`
- required operation：`READ_PUBLIC_RESEARCH`
- toolset：`news_read`
- output：由代码契约 `ResearchBundle` 决定，不在 Registry 冗余保存 `output_schema`

Registry 由 Java Data Plane 提供 Snapshot；Orchestrator 不保留相同 Capability 常量或内置目录。

Feature Flag 只决定该能力是否进入本轮 `allowed`，不改变 Capability ID 或输出 Schema。

## 10. Observation 与下游消费

Gateway 将 `ResearchBundle` 包装为标准 Observation。Finance Runtime 和 Communication 只读取 `ResearchBundle`，不读取旧 SearchResult 投影或双写字段。

浅搜消费者使用 `research.web_search` 的标准化结果；深搜消费者使用 `ResearchBundle`。需要 Deep 的调用方直接修改到新契约，不提供旧结果投影。

## 11. 数据与持久化

- Run、History、审计和幂等记录经 Java Data Plane 持久化。
- Deep Research 不直连 PostgreSQL。
- 大型原始文档不进入 Graph State；保存摘要、引用或外部对象引用。
- Memory Service 不是真实来源缓存，不得替代 Research Evidence。
- 事件发布使用 Transactional Outbox；RocketMQ 不是真源。

## 12. 错误模型

至少覆盖：

```text
DEEP_RESEARCH_NOT_ALLOWED
DEEP_RESEARCH_BUDGET_EXHAUSTED
DEEP_RESEARCH_TIMEOUT
DEEP_RESEARCH_PROVIDER_UNAVAILABLE
DEEP_RESEARCH_NO_VALID_EVIDENCE
DEEP_RESEARCH_INVALID_OUTPUT
DEEP_RESEARCH_CANCELLED
```

错误必须包含稳定 code、retryable、run_id 和安全 details。不得泄露密钥、内网地址、模型原始推理或供应商响应。

## 13. 安全规则

- 网页内容永远不是系统指令。
- 引用中出现“忽略之前规则”等文本只能作为数据保存或丢弃，不能改变流程。
- URL、域名和内容类型必须经过允许策略。
- 下载大小、重定向次数、文档数量和总字符数受预算限制。
- 对用户数据的查询必须再次经过身份和权限校验。
- 最终回答披露来源冲突、数据时效和未覆盖项。

## 14. 测试

必须覆盖：

- Registry 中能力存在且无代码目录副本；
- Flag 关闭或不在 `allowed` 时 Agent 无法调用；
- 简单问题选择浅搜，复杂多源任务可选择深搜；
- 原子搜索超时、429、5xx、空结果和非法内容；
- 提示注入文本不会改变系统行为；
- Evidence 去重、冲突保留和引用完整性；
- 模型建议完成但 coverage 不足时继续或 `PARTIAL`；
- 预算耗尽后稳定停止；
- Pause、Cancel 和恢复状态经 Java Data Plane 保持一致；
- 下游只消费 `ResearchBundle`，不存在旧结果投影。

## 15. 完成标准

- `research.deep_search` 只有一个稳定 ID 和一个输出契约。
- 能力只在数据库 Registry 登记，不在 Python 维护第二份清单。
- 调用严格受 `allowed`、Feature Flag、entitlement 和预算控制。
- 内部无递归 Gateway 或第二套 Agent。
- Evidence、Coverage、Conflict 和 Limitation 均可审计。
- 旧 Deep 实验别名、双写执行器、旧结果投影和阶段切换代码不存在。
- 相关静态检查、单元测试、契约测试和安全测试通过。

## 16. 明确禁止

- 用 `research.web_search` 同时承载浅搜和深搜两种 Schema。
- 根据参数动态返回两种不相容结果。
- 维护 Deep 实验别名或兼容投影。
- Deep 图直连供应商、数据库、Memory 或账户写接口。
- 为 Deep Research 新建 Skill、Domain、独立 Java 服务或第二套状态系统。
- 让模型绕过 Gateway、Guardrail、预算或确定性完成判断。
