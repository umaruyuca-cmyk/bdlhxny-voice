# BDLH Agent Runtime 方向升级修改意见（通用 Agent Runtime 定位）

> **文档性质：定位升级的修改意见 / 增量 ADR 草案，不是权威总架构**
> **意见版本：v1.0**
> **生效日期：2026-08-11**
> **上位架构：[00-BDLH-Agent-Runtime统一生产架构.md](../architecture/00-BDLH-Agent-Runtime统一生产架构.md)**
> **配套 Prompt：[00-BDLH-Agent-Runtime生产开发实施Prompt.md](../prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md)**
> **审查规范：[00-BDLH-Agent-Runtime生产审查规范.md](./00-BDLH-Agent-Runtime生产审查规范.md)**
> **代码事实基线：2026-08-11 工作树（`cognitive/contracts.py`、`domains/registry.py`、`tools/capabilities.py`）**
> **权威声明：本文只提出「改哪一节、加哪个 ADR、动不动代码」；发生冲突时以 00 号统一生产架构为准，本文不得作为生产决策来源**
> **执行状态（2026-08-11）：全部文档变更已完成——P0-1 ~ P0-7、P1-1 ~ P1-6、§4.4 的 M1 改名与 M7 追加、§7 两周文档包，以及 P2 中属于文档面的条目（Toolset 命名规范登记、`analysis_types` 语义重解释登记、术语与目录对照表、ADR-013）。已生效结论以 [ADR-009](../architecture/ADR-009-Runtime-Domain-Skill定位与命名.md)、[ADR-010](../architecture/ADR-010-SkillManifest与DomainDispatcher契约.md)、[ADR-011](../architecture/ADR-011-Memory分层与晋升边界.md)、[ADR-012](../architecture/ADR-012-多Skill与多Agent演进门槛.md)、[ADR-013](../architecture/ADR-013-RAG作为可插拔KnowledgeSkill的边界.md) 为准，本文相应条目仅保留为背景与验收依据**
> **仍未执行（均为代码，非文档）：`CapabilitySpec.analysis_types` 实际改名、目录收敛。`DomainRegistry` → 携带 manifest 的 Dispatcher 切片已于 2026-08-11 落地（见 §8 追加记录与 ADR-010 §6.1）**

## 0. 本文的定位与边界

本文回答一个问题：产品身份从「只读金融助手」升级为「通用 Agent Runtime / 编排内核，金融是第一个 Domain Skill」时，既有架构需要改什么。

本文遵守以下硬约束，任何违反的建议都不写入：

1. 生产 Runtime 继续 LangGraph；Letta 不进生产；
2. Mem0 / 长期记忆不作为业务真源或账本，Memory 必须分层；
3. Cognitive 不直连 MCP / Java / Web，工具必须经 Capability Registry；
4. 确定性金融计算不交给 LLM；客观研究与适配性分离；
5. 不为多 Agent 复制第二套 Tool / Capability / 观测链；
6. 不重写或废弃 M0–M6 迁移主线，只做「定位升级 + 增量扩展」；
7. RAG 不是内核中心，最多作为可插拔 Skill / Capability；
8. 对外金融能力保持只读；用户资料写入不走 Agent Capability。

本文**不提供**第二套分层图正文、第二套契约定义、第二条产品主线。

## 1. 结论

**是否需要重做架构：否。**

理由一句话：现有内核缝合线（`CognitiveAction → DomainRequest/DomainOutcome → DomainRegistry → CapabilityRegistry(带 domain) → Observation → 四时点 Guardrail → Persistence`）已经是领域无关的通用编排内核，被金融绑住的是**命名、叙事和「第一阶段范围」的写法**，不是结构。

支撑「不需要重做」的代码事实（建议原样作为 ADR-009 的背景段）：

| 事实 | 位置 | 含义 |
|---|---|---|
| `cognitive/contracts.py` 只 `import DomainRequest` | `cognitive/contracts.py:22` | 认知层对金融零依赖，已达通用内核标准 |
| `DomainRegistry` 是 `domain → runtime` 单一映射，重复注册报错 | `domains/registry.py` | Domain Dispatcher 骨架已存在，缺的只是描述元数据 |
| `CapabilitySpec` 已有 `domain` 字段与 `toolsets` 派生 | `tools/capabilities.py:41` | 能力真源天生多域，不需要为第二个 Skill 复制 |
| 确定性引擎禁止 import 框架 | 架构 §7、`domain/` | 可移植计算核已成立 |

**建议的变更级别（按工作量从大到小）：**

| 级别 | 内容 | 占比 | 是否碰运行时 |
|---|---|---|---|
| L1 文档叙事 | 架构 §0.1/§1/§2/§5.3–5.4、Prompt §1/§5.2 的身份与范围表述 | ≈70% | 否 |
| L2 增量 ADR | ADR-009 ~ ADR-012（可选 ADR-013） | ≈20% | 否 |
| L3 契约增量 | `SkillManifest`、`DomainDescriptor`、`MemoryRecord.layer` | ≈8% | 只加声明，不改路由 |
| L4 代码切片 | `DomainRegistry` 升级为携带 manifest 的 Dispatcher（零行为变更） | ≈2% | 是，但可一键回滚 |

**M0–M6 的编号、门禁、退出条件、当前 M3 切片顺序，全部不动。**

## 2. 现状对齐

### 2.1 已经是 Runtime 内核（保留，本次不改结构）

| 内核组件 | 代码位置 | 为什么已经通用 |
|---|---|---|
| InputEvent / CognitiveAction / Action Policy | `cognitive/contracts.py` | 九种行动是通用 Agent 语义，无金融词 |
| DomainRequest / DomainOutcome / DomainError | `domains/contracts.py` | 跨层唯一边界，`domain` 是字符串而非枚举 |
| Domain Dispatcher 骨架 | `domains/registry.py` | 注册即扩展 |
| Capability Registry / Toolset 派生 | `tools/capabilities.py`、`tools/toolsets.py` | 唯一能力真源 + 分域 + 派生视图 |
| Observation / Normalizer / Coverage / Provenance | `observations/` | 「外部数据必须先标准化」是通用内核规则 |
| 四时点 Guardrail 契约 | `guardrails/contracts.py` | Plan / Action / Data-quality / Response 与领域无关 |
| 标识符语义与幂等键 | 架构 §8.1、§13.4 | run / thread / session / request / task / observation / capability_execution 是 Runtime 级资产 |
| 预算 / 降级 / 审计 / SLO / 持久化门禁 | 架构 §13、§15、§16、§19 | 迁移价值最高，且完全不金融 |

这张表就是脱离金融场景后仍然成立的部分，也是对外叙事应当引用的内容。

### 2.2 过紧绑定「金融生产系统」身份（需改叙事或轻解耦）

| # | 现状 | 问题 | 处置级别 |
|---|---|---|---|
| A | 架构 §1 主线把 `Finance Runtime` 写成固定的一层 | 读者会认为内核只能跑金融；实际它是 Dispatcher 下的一个实例 | 叙事（L1） |
| B | 架构 §2.1「当前生产范围 = 只读金融助手能力」（P0-3 执行后已移为 §2.2.1） | 把 Domain 范围写成了系统范围，缺「内核范围 / 域范围」两张表 | 叙事（L1） |
| C | 架构 §2.3 非目标写「禁止任意动态加载第三方 Skill」 | 表述过宽，与「可挂更多 Skill」冲突 | 收敛为「禁止运行时动态加载未经审查的 Skill；一等 Skill 必须编译期注册」（L1） |
| D | `CapabilitySpec.analysis_types` 用金融分析词做选择器 | 内核字段带域词汇，第二个 Skill 会被迫塞金融值 | 语义重解释为 `skill_scope`；本轮只在 ADR 登记，不改名（P2） |
| E | Toolset 名全是金融词（`market_read` 等） | 同上，但影响更小（Toolset 是派生视图） | 不改；ADR 记录新增命名规则（P2） |
| F | Skill 的定义只存在于架构 §5.4 的文字列表 | 无可校验声明，第二个 Skill 只能靠人肉遵守 | 契约增量 `SkillManifest`（L3） |
| G | 域如何声明支持哪些 intent / Skill / 启用状态，没有出口 | Dispatcher 无法在不 import finance 的情况下拒绝或路由 | 契约增量 `DomainDescriptor`（L3） |
| H | Memory 只有「Mem0 可选、非真源」一句 + `MemoryStore` 三方法 | 缺分层与晋升边界；`MEMORY_CONFIRMED` 定义偏松 | ADR-011（L2） |
| I | 没有「内核不得 import 域」的自动门禁 | 叙事说通用，测试不保证 | 加一条 import 边界测试（P1，测试而非运行时） |
| J | `runtimes/langgraph/` 与 `runtime/`、`domain/` 与 `domains/` 并存 | 对外讲「Runtime 内核」时目录名自我打脸 | 不动（架构 §7 已明确延后）；仅在叙事文档给术语对照表（P2） |

### 2.3 与目标定位的差距表

| 维度 | 目标定位 | 现状 | 差距级别 | 处置 |
|---|---|---|---|---|
| 产品身份 | 通用 Agent Runtime / 编排内核 | 文档自述为「只读金融助手生产架构」 | 叙事 | L1 + ADR-009 |
| Skill 可插拔性 | 第二个 Skill 只写业务，不碰内核 | 结构支持，无声明契约与注册门禁 | 契约 | L3 + ADR-010 |
| Domain 扩展 | 新 domain 注册即接入 Dispatcher | 可注册，但无 descriptor / intent 声明 | 契约 | L3 |
| Memory 分层 | 五层，业务真源不在记忆 | 规则正确但只有一层描述 | ADR | ADR-011 |
| RAG | 可插拔 Skill / Capability，不进内核 | 当前没有，风险是未来被塞进 Cognitive | 预防 | ADR-013（可选） |
| 多 Agent | 后续可选，不是当前身份 | 文档未表态，容易被误读 | 预防 | ADR-012 |
| 可带走性 | 内核叙事与金融解耦 | 内核层无一处 import finance（已达标），但文档未证明 | 叙事 + 测试 | L1 + P1-3 |

## 3. 目标逻辑架构（增量，不是新系统）

```text
API / Auth                        [内核] JWT、身份、run/thread/session 绑定、SSE
  ↓
Cognitive Runtime                 [内核] InputEvent → CognitiveState → CognitiveAction
  ↓ (INVOKE_DOMAIN + DomainRequest)
Domain Dispatcher                 [内核] DomainRegistry + DomainDescriptor，按 domain 路由与拒绝
  ↓
Domain Runtime = Skill 宿主        [域]   例：finance；未来 knowledge、credit…
  ↓ (SkillManifest 选择)
Skill(s)                          [域]   stock-research / portfolio-health / suitability-evaluation
  ↓
Capability Gateway                [内核] Capability Registry（唯一真源）→ Adapter
  ↓
Observation Layer                 [内核] Normalizer / Coverage / Provenance / data_mode
  ↓
Communication + Guardrail         [内核] 四时点 Guardrail 是横切，不是一层；Communication 只表达
  ↓
Persistence                       [内核] Checkpoint / Session / Run / History / Audit / Task
```

本次升级的全部结构含义只有三条：

1. **Guardrail 是横切能力，不是链上一环。** 它挂在 Plan / Action / Data-quality / Response 四个时点，任何新 Skill 自动继承，不允许 Skill 自带私有 Guardrail。
2. **Domain Runtime 是 Skill 宿主，不是业务实现。** 它只做：校验 → 选 Skill → 授权求交 → 调 Capability → 组装 Outcome；业务逻辑在 Skill 与确定性引擎里。
3. **Skill 只能向下看到 Capability Gateway。** Skill 不知道 MCP、URL、供应商，也不知道自己被哪个 Cognitive 调用。

各扩展点挂载位置：

| 扩展物 | 挂在哪一层 | 需要新增什么 | 不允许什么 |
|---|---|---|---|
| Finance（现在） | Domain Runtime `finance` + 3 个 Skill | 一份 `DomainDescriptor` + 3 份 `SkillManifest` | 不改 Finance 内部实现 |
| 第二个 Skill（同域） | `finance` 域内新增 Skill | 一份 manifest + 复用现有 Toolset | 不新增 Capability Registry |
| 第二个 Domain（非金融） | 注册到 Dispatcher 的新 domain | descriptor + manifest + 自己的确定性引擎 | 不新增 Observation / Guardrail / 审计链 |
| RAG | 某 domain 下的 `knowledge-retrieval` Skill，检索结果走 Observation → Evidence | `KnowledgeQueryRequest / Outcome` 命名占位 | 不做内核中心；不让 Cognitive 直接检索；检索文本按不可信外部输入处理（架构 §10.4） |
| 多 Agent（未来） | **Cognitive Runtime 内部**的角色子图（Planner / Executor / Critic） | 角色声明 + 预算切分 | 不新增部署单元、不新增 Tool 层、不允许 Agent 间自由对话、不允许 Agent 直连 Capability |

## 4. 必须新增/修改的设计点

### 4.1 Skill 插件契约（`SkillManifest`）

最小字段集（只定语义，实现放后续切片）：

| 分组 | 字段 | 说明 |
|---|---|---|
| 身份 | `skill_id`、`skill_version`、`domain`、`status` | `status` 复用架构 §0.2 的 `CURRENT/FOUNDATION/TARGET/EXPERIMENTAL/RETIRED` |
| 输入 | `request_contract`、`accepted_intents`、`input_constraints` | 例：finance 的「恰好一个 instrument」在这里声明，而不是散在 Prompt 文字里 |
| 输出 | `result_contract`、`authority_field` | `authority_field` 显式指明权威载荷（如 `stock_research_result`），从契约层杜绝双源真相 |
| 权限 | `required_operations`、`optional_operations` | 精确 `DomainOperation`，禁止前缀授权 |
| 工具面 | `required_toolsets`、`required_capabilities`、`optional_capabilities` | 必须能在启动时对 Capability Registry 逐项校验 |
| 数据条件 | `required_data_modes`、`completeness_policy` | 例：Suitability 拒绝 `MOCK / UNAVAILABLE` |
| 预算 | `budget_profile` | **复用 `DomainBudget`，不新增第二套预算模型** |
| 降级 | `degradation_rules`、`on_missing_optional`、`on_budget_exhausted` | 映射到既有 `PARTIAL / LIMITED / FAILED` |
| 幂等 | `idempotency_keys`、`side_effects`（v1 必须为空 = 只读） | 写能力将来必须显式声明并单独审查 |
| 观测 | `audit_codes`、`stable_error_codes` | 稳定错误码进 manifest，避免散落 |

三条硬规则：

- Manifest 是**编译期注册**的一等对象（Python 声明 + 启动校验），不是运行时从磁盘或网络加载的 Prompt 文件；
- 启动时 manifest 与 Capability Registry 不一致 → **fail-fast**，不允许运行时静默跳过；
- Manifest 不得包含任何供应商名、URL、MCP tool 名。

### 4.2 Memory 分层（五层，其中一层不是记忆）

| 层 | 名称 | 权威载体 | 生命周期 | 允许驱动的决策 | 硬禁止 |
|---|---|---|---|---|---|
| L0 | 工作记忆 | Graph State / Checkpoint | 单 run / 多轮线程 | 全部本轮决策 | 不存 Token、账本、原始供应商响应 |
| L1 | 会话记录 | PostgreSQL Chat Session | 会话级 | 上下文继承、受控指代（Prompt §11.4.2.1 的 `context_entity_ref`） | 不作为金融事实 |
| L2 | 检索知识（RAG） | 向量库 / 文档源，**作为 Skill** | 可重建 | 仅作 Evidence 候选，必须带 provenance | 不进 Cognitive 直连；不作为身份或账本权威 |
| L3 | 长期语义 | Mem0 | 长期、可删除 | 只做偏好类**低影响**提示；进 `required_conditions` / `limitations` | 不驱动高影响规则；不产生 `SUITABLE` |
| L4 | 业务真源（**不是记忆**） | Java 用户事实 v2 / PG 账本 / 审计 | 版本化、可审计 | 全部高影响规则 | 不接受任何记忆层「晋升」为真源 |

晋升（promotion）规则，是当前文档最缺的一条：

```text
L3(Mem0 推断) ──不能直接──> L4(业务真源)
L3 → 只能生成「待确认项」 → 用户经独立认证的资料确认 API 确认
   → Java 生成 profile_version + confirmation_ref → 才成为 L4
```

据此建议**收紧 `MEMORY_CONFIRMED` 的定义**：必须携带服务端 `confirmation_ref`，否则等同 `INFERRED`。该结论写入 ADR-011 并回填 Prompt §10.4.2 的来源优先级表。

### 4.3 多 Skill 与多 Agent 的演进顺序

严格阶梯，不允许跳级：

| 级 | 形态 | 进入门槛 | 明确禁止 |
|---|---|---|---|
| S1 | 单 domain 多 Skill（现在） | manifest 契约就位 + M3/M4 完成 | 为新 Skill 复制 Capability / Observation / Guardrail |
| S2 | 多 domain（第二个非金融 domain） | Dispatcher 带 descriptor；「内核不 import 域」的 import 测试常绿 | 第二个 domain 自建 Adapter 层或自建审计 |
| S3 | Cognitive 内多角色子图（Planner / Executor / Critic） | 单角色路径已灰度稳定；预算可按角色切分并统一计数 | 角色各自持有工具；角色间自由对话；角色输出绕过 Response Guardrail |
| S4 | 真正的多 Agent（独立进程 / 信任域） | 出现真实需求：并发隔离、不同信任域、独立 SLA、跨组织协作 | 第二套 Tool / Capability / 观测链；Agent 直连 MCP；用多 Agent 掩盖单 Runtime 的编排缺陷 |

判断句（建议原文写进 ADR-012）：**多 Agent 的价值来自隔离，不是来自角色扮演；无隔离需求时，多角色应实现为同一 Runtime 内的子图。**

### 4.4 与现有 M0–M6 的映射

| 阶段 | 处置 | 具体说明 |
|---|---|---|
| M0 | **不动** | 生产基线门禁与本次升级无关 |
| M1 | **改名 + 补一句定位** | 「领域边界接线」副标题加「= Skill/Domain 插件边界的第一次落地」；已实现内容不改 |
| M2 | **不动** | `authority_field` 概念来自 M2 的双写治理，只在 ADR-010 引用 |
| M3 | **不动，绝对不插队** | 当前切片仍是 `PortfolioValuationBuilder`；本升级不得改变 M3 范围或验收 |
| M4 | **补一句约束** | Action Policy 必须领域无关：不得 import 任何 `domains.finance` 符号（配 import 测试） |
| M5 | **不动** | 灰度门禁不变 |
| M6 | **不动** | Task / Scheduler 不变 |
| **M7（新增，排在末尾）** | 新增 | 「第二个 Skill / Domain 骨架验证」，只验证插件契约可用，不带业务价值目标；不允许提前到 M4 之前 |

原则：**只在主线末尾追加编号，绝不在 M0–M6 之间插入新编号**，否则既有阶段报告与门禁引用的编号语义全部漂移。

### 4.5 对外叙事与对内工程真源的隔离

| 用途 | 载体 | 允许说什么 | 禁止 |
|---|---|---|---|
| 简历一句话 | 简历（仓库外） | 「通用 Agent Runtime / 编排内核：认知编排 + 领域 Skill 插件 + 统一能力网关 + 四时点治理 + 可复现确定性计算；金融研究是首个 Skill」 | 不写「多 Agent 平台」「RAG 平台」 |
| 面试 5 分钟版 | 新增 `docs/architecture/01-BDLH-Agent-Runtime定位与Skill扩展说明.md`（定位说明，非权威架构） | 内核/域边界、为什么 LLM 不做确定性计算、Memory 五层、可插拔证据 | 不重复架构 §1 主线正文、不给第二套分层图 |
| 工程真源 | `00-BDLH-Agent-Runtime统一生产架构.md` | 一切生产决策 | 不写职业叙事、不写未来多 Agent 蓝图 |

隔离机制：01 号文档头部必须声明「本文不是生产决策来源，冲突时以 00 号为准」，并在架构 §22 历史文档处置表登记 01 号的定位。

## 5. 修改意见清单（可执行）

### P0（已于 2026-08-11 全部执行，纯文档 + ADR，零代码）

| # | 动作 | 目标位置 | 新契约 | 验收 |
|---|---|---|---|---|
| P0-1 | 在文档头与 §1 之前加「产品身份」段：通用 Agent Runtime，Finance 是第一个 Domain Skill | 架构 §0.1 前 / §1 开头 | 无 | 读者读完 §1 能说出「内核 ≠ 金融」 |
| P0-2 | §1 主线改为 `… → Domain Dispatcher → Domain Runtime(Skill 宿主) → Skill → Capability Gateway → …`，注明「当前唯一实例：finance」 | 架构 §1 | 无 | 主线中不再出现「Finance Runtime 是固定层」的读法 |
| P0-3 | §2 拆为「2.1 内核能力范围 / 2.2 首个 Domain（金融）范围 / 2.3 非目标」 | 架构 §2 | 无 | 域范围变化不再需要改内核范围表 |
| P0-4 | §2.3 非目标精确化：禁止的是「运行时动态加载未审查 Skill」 | 架构 §2.3 | 无 | 与「可挂更多 Skill」不再冲突 |
| P0-5 | 新增 **ADR-009：Runtime / Domain / Skill 三层定位与命名**（含 §2.1 代码事实表作为背景） | `docs/architecture/ADR-009-*.md` | 无 | 状态 `APPROVED`，并在架构 §23 登记 |
| P0-6 | 新增 **ADR-011：Memory 五层与晋升边界**（含 `MEMORY_CONFIRMED` 收紧） | `docs/architecture/ADR-011-*.md` | 无 | Prompt §10.4.2 来源优先级表可据其回填 |
| P0-7 | Prompt §1、§5.2 各加一句：Cognitive 与 Domain Dispatcher 是领域无关内核，实现时不得 import 具体域符号 | Prompt §1、§5.2 | 无 | 后续任务 Prompt 天然带上该约束 |

### P1（已于 2026-08-11 全部执行，ADR + 契约声明 + 一条测试门禁）

| # | 动作 | 目标位置 | 新契约（仅名称与目的） | 验收 |
|---|---|---|---|---|
| P1-1 | 新增 **ADR-010：Skill Manifest 与 Domain Dispatcher 契约** | `docs/architecture/ADR-010-*.md` | `SkillManifest`（Skill 自描述与启动校验）、`DomainDescriptor`（域声明支持的 intent / Skill / 启用状态） | 字段表冻结；明确「编译期注册 + 启动 fail-fast」 |
| P1-2 | 新增 **ADR-012：多 Skill 与多 Agent 演进门槛**（S1–S4 阶梯 + 禁止复制清单） | `docs/architecture/ADR-012-*.md` | 无 | 未来任何「加个 Agent」提案可被该 ADR 直接判定 |
| P1-3 | 加一条**内核纯净度 import 测试**：`cognitive/`、`domains/contracts.py`、`domains/registry.py`、`guardrails/`、`observations/` 不得 import `domains.finance` 或金融确定性计算模块 | 测试目录（不改运行时） | 无 | 测试常绿；违规在回归中直接失败 |
| P1-4 | 架构 §5.4 把 Skill 声明清单替换为「见 `SkillManifest` 字段表」引用 | 架构 §5.4 | 无 | 单一真源，不再有文字版与契约版两套 |
| P1-5 | 架构 §9 Memory 段落引用 ADR-011 五层表 | 架构 §9.1 | `MemoryRecord.layer`（标注记忆来源层，仅声明） | 表格中 Mem0 行明确标注 L3 |
| P1-6 | Prompt §11 补一句：M4 Action Policy 与 Communication 不得依赖具体域枚举 | Prompt §11.3 | 无 | M4 交付报告可验证 |

### P2（等 M3/M4 落地后再考虑，现在只登记）

| # | 动作 | 说明 |
|---|---|---|
| P2-1 | `CapabilitySpec.analysis_types` 语义重命名为 `skill_scopes` | 纯重命名 + 迁移，收益低风险中，不在本轮做 |
| P2-2 | Toolset 命名规范 `{domain}_{scope}_{read|compute}` | 仅对**新增** Toolset 生效，不回改现有六个 |
| P2-3 | `domain/` 与 `domains/`、`runtime/` 与 `runtimes/` 目录收敛 | 架构 §7 已明确延后；本轮只在 01 号文档给术语对照表 |
| P2-4 | 可选 **ADR-013：RAG 作为可插拔 Knowledge Skill 的边界** | 仅当真的要做 RAG 时再写；提前写会诱发 scope 膨胀 |
| P2-5 | M7 第二个 Skill / Domain 骨架 | 排在 M6 之后，不得提前 |

### 明确「不改什么」

- 不换生产 Runtime，继续 LangGraph；Letta 仍只在隔离实验环境；
- 不动 M0–M6 的编号、范围、退出门槛、`RELEASE_BLOCKED` 规则；
- 不打断当前 M3 切片顺序（`PortfolioValuationBuilder` → Snapshot → ADR-004 → Engine）；
- 不改 `DomainRequest / DomainOutcome / FinancialDomainRequest / StockResearchResult / SuitabilityAssessment` 的既有字段语义；
- 不新增第二套 Capability / Toolset / Observation / Guardrail / 预算 / 审计模型；
- 不为「通用性」把 `FinancialIntent` 上提到内核层，它应留在 finance 私有契约；
- 不在本轮做任何目录重命名、批量格式化或 Decimal 化；
- 不新增 API 路由、不新增 SSE 事件类型；
- 不把 RAG、多 Agent、Skill 市场写进 00 号文档正文。

## 6. 反模式

1. **「通用化」变成大重构。** 为了显得通用而重命名目录、上提枚举、抽象基类满天飞，收益全在文档，风险全在代码。通用性由缝合线保证，不由命名保证。
2. **内核偷偷 import 域。** 一次 `from domains.finance import FinancialIntent` 写进 Cognitive，通用叙事当场作废。这是 P1-3 import 测试存在的唯一理由。
3. **第二个 Skill 复制第一套基础设施。** 新 Skill 自带 HTTP 客户端、自带日志字段、自带 Guardrail，随即出现两套观测链，之后再也合不回去。
4. **多 Agent 当身份牌打。** 单 Runtime 编排尚未灰度稳定就引入多 Agent，只会把「编排能力不足」包装成「架构很酷」，并复制第二套 Tool 层。
5. **Mem0 悄悄变账本。** 从「记忆里有用户风险偏好」到「用它跑 Suitability」只有一次 code review 的距离，必须靠 L3→L4 晋升需 `confirmation_ref` 拦住。
6. **RAG 上位成内核中心。** 一旦 Cognitive 直接检索并把命中文本当结论，Observation / Evidence / Provenance 三层治理全部旁路，Prompt Injection 面直通模型。
7. **Skill 变成可动态加载的 Prompt 文件。** 「插件」听起来就想做热加载，那等于把权限、预算、审计边界交给磁盘上的文本；必须坚持编译期注册 + 启动校验。
8. **叙事污染工程真源。** 把「未来多 Agent / Skill 生态」写进 00 号文档，导致后续实施任务照着未落地蓝图开发，`TARGET` 与 `CURRENT` 再次混淆。
9. **给通用性新开阶段编号并插进 M0–M6 中间。** 既有门禁引用与阶段报告的编号语义全部漂移；只能追加 M7。
10. **manifest 与 Registry 双源不一致。** manifest 写了能力名却不校验，Skill 运行时静默跳过某能力，最后仍输出 `COMPLETE`；必须启动 fail-fast。
11. **为了域无关把确定性计算也抽象掉。** 金融指标应留在 finance 的确定性引擎里；内核只保证「LLM 不做确定性计算」这条规则，不需要通用计算框架。
12. **用「第二个 Skill」偷偷扩业务范围。** 第二个 Skill 的目标只能是验证插件契约（M7）；一旦给它设业务 KPI，就变成第二条产品主线，M0–M6 主线随之失焦。

## 7. 建议的下一步（仅规划）

### 两周最小文档变更包

| 周 | 交付物 | 工作量 | 是否碰代码 |
|---|---|---|---|
| 第 1 周 | P0-1 ~ P0-4（架构 §0/§1/§2 叙事修订，四处小改） | 半天 | 否 |
| 第 1 周 | ADR-009（定位与命名）、ADR-011（Memory 五层与晋升） | 1 天 | 否 |
| 第 1 周 | P0-7（Prompt §1/§5.2 各加一句领域无关约束） | 半小时 | 否 |
| 第 2 周 | ADR-010（`SkillManifest` / `DomainDescriptor` 字段表冻结）、ADR-012（S1–S4 阶梯） | 1 天 | 否 |
| 第 2 周 | 新增 `01-BDLH-Agent-Runtime定位与Skill扩展说明.md`（对外叙事，头部声明非权威） | 半天 | 否 |
| 第 2 周 | P1-3 内核纯净度 import 测试 | 1 小时 | 只加测试 |
| 第 2 周 | 在架构 §22 / §23 登记 01 号文档与 ADR-009 ~ ADR-012 | 15 分钟 | 否 |

两周结束时的状态：定位已升级、扩展面已可讲、内核纯净度已由测试保证，而运行时一行未改，M3 进度零影响。

### 之后的第一个代码切片

不是写第二个 Skill，而是：

```text
切片：DomainRegistry → 携带描述元数据的 Domain Dispatcher
范围：domains/registry.py + finance 的一份 DomainDescriptor + 三份 SkillManifest（声明现状，不改行为）
时点：当前 M3 切片（PortfolioValuationBuilder）交付并停止之后、M4 开始之前
规模：≤1 天，零对外行为变更
验收：① 启动时 manifest 与 Capability Registry 逐项校验，不一致则 fail-fast；
      ② Dispatcher 对未注册 domain / 未启用 intent 返回稳定 ACTION_NOT_ENABLED；
      ③ 全量回归通过，默认路径与非默认 Finance Runtime 行为不变；
      ④ 内核纯净度 import 测试仍常绿。
回滚：移除 descriptor / manifest 注册与校验调用即回到现状。
不做：不改 Finance 内部实现、不改任何契约字段语义、不写第二个 Skill、不改 Toolset 命名。
```

选它的理由：它是「Skill 可插拔」这一叙事唯一必需的代码事实。有了它，「新 Skill 只写业务、内核不动」这句话有 manifest 与启动校验作证；而它本身不产生业务风险，也不动 M0–M6 任何门禁。

## 8. 文档收口记录（2026-08-11）

两周文档包被一次性执行完毕，实际交付超出上表范围，追加部分如下：

| 交付物 | 位置 | 说明 |
|---|---|---|
| ADR-013 | `docs/architecture/ADR-013-...md` | 只冻结 RAG 边界，状态标注「实施未排期」，避免提前立项引发范围膨胀 |
| M1 改名 + M7 追加 | 架构 §18；Prompt §0/§3.1/§8 | M7 为可选插件契约验证，排在末尾，明确不得抢占 M0–M6 |
| 状态表与代码组织补录 | 架构 §3、§7 | 登记 Domain Dispatcher、`SkillManifest`/`DomainDescriptor`（`TARGET`）与内核纯净度门禁 |
| 测试层次登记 | 架构 §19.1；Prompt §19.1 | 把「架构边界测试」列入常规回归项，绑定 ADR-009 §3.3 |
| `MEMORY_CONFIRMED` 回填 | Prompt §10.4.2、§10.4.4 | 补齐 `confirmation_ref` 要求与「记忆层不参与真实性推导」 |
| 配套架构图对齐 | `00-BDLH-Agent-Runtime生产架构.drawio` | 仅改标签（内核泳道、Domain Dispatcher、Domain Runtime、Mem0 L3），未重排布局 |
| 根 README 重写 | `README.md` | 原内容仍是旧 Java Agent + RAG 叙事，且文档索引指向十余个已删除文件，全部替换为当前定位与真实路径 |

结论：文档面不再有与新定位冲突的表述，剩余全部为代码切片，按 §7 的时点执行。

### 8.1 Dispatcher 切片执行记录（2026-08-11，§7 钦定的第一个代码切片）

ADR-010 §6 的独立代码切片已落地，零对外行为变更，全量回归通过。

本切片的权威执行记录（交付物清单、验收结论）以 [ADR-010 §6.1](../architecture/ADR-010-SkillManifest与DomainDispatcher契约.md) 为准，本文不重复。要点：`DomainRegistry` 升级为携带 descriptor 的 Dispatcher；finance 补一份 descriptor + 三份 manifest（声明现状）；启动 fail-fast 校验落地；M3 估值能力补注册。

至此，§7 的「第一个代码切片」完成，「Skill 可插拔」叙事由 manifest 与启动校验作证。剩余代码切片为 P2 批次（`analysis_types` 改名、目录收敛），排在 M3 收尾之后。
