# ADR-011：Memory 分层与晋升边界

> 状态：APPROVED
> 批准人：项目 owner
> 日期：2026-08-11
> 影响：[00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) §9.1；[00-BDLH-Agent-Runtime生产开发实施Prompt.md](../prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md) §10.4.2 来源优先级、§10.4.4 真实性推导
> 依据：[04-Runtime定位升级修改意见.md](../reviews/04-Runtime定位升级修改意见.md) §4.2

## 1. 决策目标

把「Mem0 是可选增强、不是业务真源」从一句原则展开为可执行的分层模型，并冻结「记忆不能自行晋升为业务真源」的边界。

本 ADR 不引入新的存储组件，不改变 Mem0 的可选与可降级地位，也不改变 `FinancialSnapshot` 的既有字段语义。

## 2. 分层模型

| 层 | 名称 | 权威载体 | 生命周期 | 允许驱动的决策 | 硬禁止 |
|---|---|---|---|---|---|
| L0 | 工作记忆 | Graph State / Checkpoint | 单 run 或多轮线程 | 本轮全部决策 | 不存 Token、账本、原始供应商响应 |
| L1 | 会话记录 | PostgreSQL Chat Session | 会话级 | 上下文继承、受控指代（Prompt §11.4.2.1 的 `context_entity_ref`） | 不作为金融事实来源 |
| L2 | 检索知识（RAG） | 向量库 / 文档源，作为 Skill 提供 | 可重建 | 仅作 Evidence 候选，必须带 provenance | 不进 Cognitive 直连；不作为身份或账本权威；不免除 §10.4 不可信输入处理 |
| L3 | 长期语义 | Mem0 | 长期、可删除 | 仅低影响偏好提示；写入 `required_conditions` 或 `limitations` | 不驱动高影响规则；不单独促成 `SUITABLE` |
| L4 | 业务真源（**不是记忆**） | Java 用户事实 v2 / PostgreSQL 账本 / 审计 | 版本化、可审计 | 全部高影响规则 | 不接受任何记忆层的自动晋升 |

L4 之所以列在同一张表里，是为了说明它**不属于记忆体系**：账本、持仓、风险画像和审计历史永远从 L4 读取，任何记忆层的相同字段都只是派生或提示。

## 3. 晋升边界

```text
L3（Mem0 推断） ──不允许直接晋升──> L4（业务真源）

允许路径：
L3 推断 → 生成「待确认项」（required_conditions / limitations）
       → 用户经独立认证的资料确认 API 提交并确认
       → Java 生成 profile_version + confirmed_at + confirmation_ref
       → 成为 L4 业务真源
```

由此收紧既有来源枚举的判定：

- `MEMORY_CONFIRMED` 必须携带服务端生成的 `confirmation_ref`；缺少确认引用时等同 `INFERRED`，只能进入 `required_conditions` 或 `limitations`；
- `INFERRED` 永远不能单独把 Suitability 结果推到 `SUITABLE`；
- 记忆层不得写入 `data_mode`、`is_mock`、`profile_version` 或 `confirmation_ref`，这些只能由服务端在 L4 产生；
- 用户资料确认入口不是 Agent Capability，不进入 Capability Registry、Toolset 或领域授权 Policy。

## 4. 降级与可删除性

- L0 / L1 / L4 属于生产关键持久化（架构 §9.3），失败必须结构化报错，不得静默降级内存；
- L2 / L3 属于增强项，失败时跳过并记录 degraded，不阻断主链路；
- L3 写入必须有明确策略与可删除性（架构 §14.3）；用户删除请求必须能清除 L3 内容与可重建的 L2 派生数据，不影响 L4 审计留存义务；
- 熔断状态、供应商错误和运行诊断不得写入 L3。

## 5. 契约影响

| 项 | 变更 | 状态 |
|---|---|---|
| `MemoryRecord` | 增加标注来源层的 `layer` 字段（仅声明，用于观测与审计） | 已落地（`memory/base.py:32`，默认 `"L3"`，引用本 ADR 的 L0–L4 分层） |
| `MemoryStore` | 接口不变，仍为 `search / get_profile / add`，失败返回空并记录 degraded | 不变 |
| `FinancialSnapshot` | 字段不变；来源判定按本 ADR 收紧 `MEMORY_CONFIRMED` | 不变 |

## 6. 后果

正面：

- 「记忆变账本」这一类事故有了可引用的拦截规则，而不是靠评审记性；
- RAG 未来接入时，其位置（L2、作为 Skill）已经预先固定，不会滑向内核中心；
- 高影响规则的输入来源可枚举、可测试。

代价与风险：

- `MemoryRecord.layer` 字段虽已落地（`memory/base.py:32`，默认 `"L3"`），但它只是观测/审计标注，**不驱动召回行为**——分层规则的实际约束力仍由本 ADR 的晋升边界与 `MEMORY_CONFIRMED` 收紧条款保证，而非靠字段本身；
- `MEMORY_CONFIRMED` 收紧后，若确认 Provider 尚未实现，相关正常路径保持不开放，个性化能力覆盖面会更窄。这是有意的 fail-closed 选择。
