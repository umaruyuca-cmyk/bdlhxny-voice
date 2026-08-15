# ADR-009：Runtime / Domain / Skill 三层定位与命名

> 状态：APPROVED
> 批准人：项目 owner
> 日期：2026-08-11
> 影响：[00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) 产品身份声明、§1、§2；[00-BDLH-Agent-Runtime生产开发实施Prompt.md](../prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md) §1、§5.2
> 依据：[04-Runtime定位升级修改意见.md](../reviews/04-Runtime定位升级修改意见.md) §1、§2、§3

## 1. 决策目标

把产品身份从「只读金融助手生产系统」升级为「通用 Agent Runtime / 编排内核 + 领域 Skill 插件」，并冻结内核、Domain、Skill 三层的职责与命名规则。

本 ADR 只改变定位、命名与扩展面。它不改变 §18 的 M0–M6 迁移主线、阶段门禁、退出条件，也不改变任何已有跨层契约的字段语义。

## 2. 背景：为什么不需要重做架构

2026-08-11 工作树的代码事实表明内核缝合线已经领域无关：

| 事实 | 位置 | 含义 |
|---|---|---|
| `cognitive/contracts.py` 只 import 通用 `DomainRequest` | `cognitive/contracts.py:22` | 认知层对金融零依赖 |
| `DomainRegistry` 是 `domain → runtime` 单一映射，重复注册报错 | `domains/registry.py` | Domain Dispatcher 骨架已存在 |
| `CapabilitySpec` 已含 `domain` 字段与 `toolsets` 派生 | `tools/capabilities.py:41` | 能力真源天生多域 |
| `domain/` 禁止 import LangGraph / LangChain / MCP / Mem0 / FastAPI | 架构 §7 | 确定性计算核可移植 |

被金融绑住的是命名、叙事和「第一阶段范围」的写法，不是结构。因此本次为定位升级，不是架构重做。

## 3. 决策

### 3.1 三层职责

| 层 | 归属 | 职责 | 硬约束 |
|---|---|---|---|
| Runtime（内核） | 与领域无关 | 身份、认知编排、Domain 调度、Capability 网关、Observation、四时点 Guardrail、Communication、持久化、预算与观测 | 不得依赖任何具体领域的枚举、契约或计算模块 |
| Domain Runtime | 领域 | Skill 宿主：校验请求、选择 Skill、授权求交、调用 Capability、组装 Outcome | 不实现业务算法；不直接拼供应商协议 |
| Skill | 领域 | 单一业务能力的实现，配合确定性引擎产出结构化结果 | 只能向下看到 Capability Gateway；不知道供应商、URL、MCP tool 名 |

当前唯一 Domain 是 `finance`，其 Skill 为 `stock-research`、`portfolio-health`、`suitability-evaluation`。

### 3.2 命名规则

- Domain 名使用稳定小写标识（如 `finance`），不含供应商或实现细节；
- Skill 名使用 `{业务动作}` 或 `{对象}-{动作}` 形式（如 `stock-research`），不含阶段号；
- 领域语义枚举保持在该领域私有契约中，例如 `FinancialIntent` 不上提到内核层；
- 新增 Toolset 使用 `{domain}_{scope}_{read|compute}` 命名；现有六个金融 Toolset 名保持不变，不做回改；
- `CapabilitySpec.analysis_types` 的语义应理解为「Skill 适用范围（skill scope）」而非金融专有分析类型；重命名列为后续可选项，本 ADR 不触发改名。

### 3.3 内核纯净度

以下模块不得 import 任何 `domains.finance` 符号或领域确定性计算模块：

```text
cognitive/
domains/contracts.py
domains/registry.py
guardrails/
observations/
```

该约束应由一条常绿的 import 边界测试保证，而不仅依赖评审（实施项，见 04 号意见 P1-3）。

### 3.4 Guardrail 的位置

四时点 Guardrails 是横切治理，不是主线上的某一层。任何新增 Skill 自动继承，不得自带私有 Guardrail，也不得绕过 Response Guardrail 直接对外表达。

## 4. 明确不改变的内容

- 生产 Runtime 继续 LangGraph；Letta 仍只限隔离实验环境；
- M0–M6 编号、范围、退出门槛与 `RELEASE_BLOCKED` 规则不变；当前 M3 切片顺序不受影响；
- `DomainRequest / DomainOutcome / FinancialDomainRequest / StockResearchResult / SuitabilityAssessment` 既有字段语义不变；
- 不新增第二套 Capability / Toolset / Observation / Guardrail / 预算 / 审计模型；
- 不新增 API 路由或 SSE 事件类型；
- 不做目录重命名（`domain/` 与 `domains/`、`runtime/` 与 `runtimes/` 的收敛仍按架构 §7 延后）。

## 5. 后果

正面：

- 新增 Skill 或 Domain 只需注册，不需要改内核；
- 内核部分可独立于金融场景描述与迁移；
- 「内核 vs 域」的判定标准明确，评审有据可依。

代价与风险：

- 文档中「Finance Runtime」既是领域边界又是 Skill 宿主实例，需要读者理解双重身份；
- 在 `SkillManifest` 与 `DomainDescriptor` 落地前（见 ADR-010），Skill 声明仍靠文档约束，缺少启动时校验；
- 内核纯净度在 import 测试落地前仍可能被一次提交破坏。

## 6. 后续 ADR

| ADR | 主题 | 状态 |
|---|---|---|
| [ADR-010](./ADR-010-SkillManifest与DomainDispatcher契约.md) | Skill Manifest 与 Domain Dispatcher 契约 | `APPROVED`（字段表已冻结，descriptor/manifest 切片已落地；零对外行为变更） |
| [ADR-011](./ADR-011-Memory分层与晋升边界.md) | Memory 分层与晋升边界 | `APPROVED` |
| [ADR-012](./ADR-012-多Skill与多Agent演进门槛.md) | 多 Skill 与多 Agent 演进门槛 | `APPROVED` |
| [ADR-013](./ADR-013-RAG作为可插拔KnowledgeSkill的边界.md) | RAG 作为可插拔 Knowledge Skill 的边界 | `APPROVED`（边界生效，实施未排期） |
