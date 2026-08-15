# ADR-013：RAG 作为可插拔 Knowledge Skill 的边界

> 状态：APPROVED（边界约束即刻生效）
> 实施状态：未排期。本 ADR **不授权**启动任何 RAG 实施，也不新增阶段编号
> 批准人：项目 owner
> 日期：2026-08-11
> 依赖：[ADR-009](./ADR-009-Runtime-Domain-Skill定位与命名.md)、[ADR-010](./ADR-010-SkillManifest与DomainDispatcher契约.md)、[ADR-011](./ADR-011-Memory分层与晋升边界.md)
> 依据：[04-Runtime定位升级修改意见.md](../reviews/04-Runtime定位升级修改意见.md) §3、§4.2、§6

## 1. 为什么现在就写

RAG 不在当前迁移计划内，但它是最容易在「顺手加一下」的情况下滑进内核的组件：一旦认知层被允许直接检索并把命中文本当作结论，Observation、Evidence、Provenance 三层治理会被整体旁路，Prompt Injection 面直通模型。

本 ADR 的作用是**先把边界钉死**，使未来任何 RAG 提案只能沿受控路径落地。它不描述实现方案，也不构成开工许可。

## 2. 决策

### 2.1 位置

RAG 是**某个 Domain 之下的检索类 Skill**，属于 ADR-011 的 L2（检索知识）层。它不是内核组件，不是第二个编排中心，也不是记忆层的替代品。

```text
Cognitive Runtime
  → Domain Dispatcher
  → Domain Runtime
  → Knowledge Retrieval Skill        ← RAG 在这里
  → Capability Gateway（检索 Capability）
  → Observation Normalizer
  → Evidence 候选
```

### 2.2 硬约束

1. **不得由认知层直接检索。** 检索必须经 `DomainRequest` 进入领域，再经 Capability Gateway 调用，与其他外部能力同等受 Plan / Action Guardrail、授权与预算约束。
2. **检索结果必须先成为 Observation。** 携带来源、时间、质量与降级状态；未经标准化的命中文本不得进入任何 State 或提示词。
3. **检索文本是不可信外部输入。** 完整适用架构 §10.4：不得覆盖系统指令、不得改变工具白名单、不得触发新的 Capability，必须清洗与截断，引用时保留来源。
4. **不得作为身份、账本或适配性权威。** 命中内容永远是 Evidence 候选，不是业务真源；不得用于推导 `data_mode`，也不得驱动高影响规则（ADR-011）。
5. **不得替代确定性计算。** 检索到的公式、阈值或结论不能绕过确定性引擎直接产出数值判断。
6. **必须有 `SkillManifest`。** 声明其 Capability、预算、降级规则与稳定错误码，并在启动时对 Capability Registry 校验（ADR-010）。
7. **失败必须可降级。** 检索不可用属于增强项失败：跳过并写入 limitations，不阻断主链路，也不得把缺失伪装为「无相关资料」这一确定结论。
8. **知识库内容需可追溯与可删除。** 索引来源、版本与更新时间必须可查；用户相关内容的删除请求必须能连带清除派生索引。

### 2.3 明确不做

- 不把 RAG 作为系统卖点或架构中心；
- 不为 RAG 新建第二套 Observation、Guardrail、预算或审计链；
- 不在 M0–M6 之间插入 RAG 阶段；如需实施，只能作为 M7 之后的独立立项；
- 不用 RAG 掩盖数据缺失：缺行情、缺用户事实时的正确行为仍是 `LIMITED` 或 `INSUFFICIENT_INFORMATION`。

## 3. 与历史文档的关系

历史版本档案中曾把「RAG 知识库」列为核心能力（见 `docs/archive/architecture/历史版本-*.md` 与旧 README 描述）。该定位已被本 ADR 取代：RAG 是可选的可插拔 Skill，不是产品身份的一部分。

## 4. 后果

正面：未来引入 RAG 时，治理链、预算与降级语义无需重新设计；「检索命中即结论」这一类事故有明确可引用的拦截依据。

代价：RAG 落地成本高于直接把向量检索塞进提示词构建，短期内不会有「一周上线 RAG」这种选项。这是有意的取舍。
