# ADR-012：多 Skill 与多 Agent 演进门槛

> 状态：APPROVED
> 批准人：项目 owner
> 日期：2026-08-11
> 依赖：[ADR-009](./ADR-009-Runtime-Domain-Skill定位与命名.md)、[ADR-010](./ADR-010-SkillManifest与DomainDispatcher契约.md)
> 影响：[00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) §2.2.3、§5.2；未来任何「新增 Agent / 角色」提案
> 依据：[04-Runtime定位升级修改意见.md](../reviews/04-Runtime定位升级修改意见.md) §4.3、§5 P1-2

## 1. 决策目标

固定「多 Skill → 多 Domain → 多角色 → 多 Agent」的演进阶梯与每级门槛，使未来的扩展提案可以被本文直接判定，而不是每次重新辩论。

核心判断：**多 Agent 的价值来自隔离，不是来自角色扮演。无隔离需求时，多角色必须实现为同一 Runtime 内的子图。**

## 2. 演进阶梯（不允许跳级）

| 级 | 形态 | 进入门槛 | 明确禁止 |
|---|---|---|---|
| S1 | 单 Domain 多 Skill（当前所处位置） | Registry 驱动的 Skill 契约完成（ADR-010）；入口与菜单重写完成 | 为新 Skill 复制 Capability Registry、Observation、Guardrail 或审计链 |
| S2 | 多 Domain（第二个非金融 Domain） | Dispatcher 携带 `DomainDescriptor`；内核纯净度 import 测试常绿 | 第二个 Domain 自建 Adapter 层、自建观测字段或自建幂等机制 |
| S3 | Cognitive 内多角色子图（Planner / Executor / Critic） | 单角色路径完成真实环境验证；预算可按角色切分且由 Runtime 统一计数 | 角色各自持有工具；角色间自由对话；任一角色输出绕过 Response Guardrail |
| S4 | 真正的多 Agent（独立进程或信任域） | 出现真实的隔离需求（见 §3） | 第二套 Tool / Capability / 观测链；Agent 直连 MCP 或 Java；用多 Agent 掩盖单 Runtime 的编排缺陷 |

当前位置是 S1。S2 属于可选扩展，S3、S4 不在第一阶段与第二阶段范围内。

## 3. S4 的准入条件

只有出现以下**真实需求之一**才允许讨论独立 Agent，且必须先提交单独 ADR：

1. 并发隔离：某类任务的资源占用或故障会连带影响主链路，且无法用预算与熔断解决；
2. 信任域隔离：处理不同敏感级别的数据，需要独立凭证、网络策略或审计边界；
3. 独立 SLA：不同可用性或延迟目标，需要独立扩缩容与发布节奏；
4. 跨组织协作：Agent 归属不同团队或不同法律主体。

「角色分工看起来更清晰」「Prompt 更好写」「业界流行」都不构成准入理由。

## 4. 无论到哪一级都不得复制的内容

| 单一真源 | 位置 |
|---|---|
| Capability / Skill / Toolset Registry | PostgreSQL `registry` schema + Java Snapshot API |
| 菜单算法与能力网关 | `registry/menu.py`、`tools/` |
| Observation 标准化与覆盖判断 | `observations/` |
| 四时点 Guardrail | `guardrails/` |
| 预算模型 `DomainBudget` | `domains/contracts.py` |
| 标识符语义与幂等键 | 架构 §8.1、§13.4 |
| 结构化日志字段与审计码 | 架构 §15.1 |
| 持久化 Store 协议 | 架构 §9.3 |

新增 Skill、Domain、角色或 Agent 只允许**注册与复用**上述真源，不允许派生第二份实现。违反此条的提案一律拒绝，无论其业务收益。

## 5. 实施约束

- 当前只实现 S1。
- S2 需要真实第二 Domain 需求和独立验收，不创建纯占位插件。
- S3、S4 出现真实需求时另立 ADR；当前代码不预留半成品角色或第二进程。

## 6. 后果

正面：扩展提案有可引用的判定标准；「多 Agent」不再是含糊的架构愿景，而是一个有准入条件的选项；单一真源清单让复制行为在评审中可被直接指出。

代价：短期内不能用多 Agent 叙事包装项目；某些看起来自然的角色拆分会被推迟到 S3，需要用子图而非独立 Agent 实现。
