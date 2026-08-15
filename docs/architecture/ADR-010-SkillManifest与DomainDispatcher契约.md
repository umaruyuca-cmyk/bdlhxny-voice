# ADR-010：Skill Manifest 与 Domain Dispatcher 契约

> 状态：APPROVED（字段表已冻结；§6 实现已落地——descriptor/manifest 切片，2026-08-11）
> 批准人：项目 owner
> 日期：2026-08-11
> 依赖：[ADR-009](./ADR-009-Runtime-Domain-Skill定位与命名.md)
> 影响：[00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) §5.4、§10.1；`domains/registry.py`、`domains/finance/`
> 依据：[04-Runtime定位升级修改意见.md](../reviews/04-Runtime定位升级修改意见.md) §4.1、§5 P1-1

## 1. 决策目标

冻结 Skill 的自描述契约（`SkillManifest`）与 Domain 的自描述契约（`DomainDescriptor`）字段表，使「新增 Skill 只写业务、内核不动」成为可在启动时校验的事实，而不是靠评审记忆。

本 ADR 只冻结字段与规则。实现属于独立代码切片（见 §6），不改变任何现有运行时行为，也不改变 M0–M6 阶段顺序。

## 2. 为什么需要它

架构 §5.4 目前用自然语言列出「每个 Skill 必须声明输入、输出、Toolset、权限、数据完成条件、预算、降级、幂等」。该清单无法被程序校验，导致：

- 第二个 Skill 是否遵守，只能人工审查；
- 「谁是权威输出载荷」这类已在 M2 付出代价的问题（`analysis_result` 与 `stock_research_result` 双写）没有契约层表达；
- Skill 声明的 Capability 名与 Capability Registry 不一致时，只能在运行时暴露。

## 3. `SkillManifest` 字段表（冻结）

| 分组 | 字段 | 类型语义 | 说明 |
|---|---|---|---|
| 身份 | `skill_id` | 稳定字符串 | 全局唯一，发布后不得复用为其他语义 |
| 身份 | `skill_version` | 语义化版本 | 规则或输出结构变化必须递增 |
| 身份 | `domain` | 稳定字符串 | 必须是已注册 Domain |
| 身份 | `status` | 枚举 | 复用架构 §0.2 的 `CURRENT / FOUNDATION / TARGET / EXPERIMENTAL / RETIRED` |
| 输入 | `request_contract` | 契约引用 | 指向严格 Pydantic 模型名 |
| 输入 | `accepted_intents` | 集合 | 该 Skill 可处理的领域意图；空集表示不由意图触发 |
| 输入 | `input_constraints` | 结构化约束 | 例：`instrument_count == 1`；禁止写成自由文本 |
| 输出 | `result_contract` | 契约引用 | 指向严格 Pydantic 模型名 |
| 输出 | `authority_field` | 字段路径 | Outcome 上的权威载荷字段，杜绝双源真相 |
| 权限 | `required_operations` | 精确 `DomainOperation` 集合 | 禁止前缀授权 |
| 权限 | `optional_operations` | 精确 `DomainOperation` 集合 | 缺失时降级而非失败 |
| 工具面 | `required_toolsets` | Toolset 名集合 | 必须存在于派生视图 |
| 工具面 | `required_capabilities` | 精确 Capability 名集合 | 启动时逐项对 Registry 校验 |
| 工具面 | `optional_capabilities` | 精确 Capability 名集合 | 同上 |
| 数据条件 | `required_data_modes` | `data_mode` 集合 | 例：Suitability 排除 `MOCK / UNAVAILABLE` |
| 数据条件 | `completeness_policy` | 结构化规则 | 关键字段缺失时的稳定行为 |
| 预算 | `budget_profile` | `DomainBudget` 默认值引用 | **复用 `DomainBudget`，禁止第二套预算模型** |
| 降级 | `degradation_rules` | 规则集合 | 映射到既有 `PARTIAL / LIMITED / FAILED` |
| 降级 | `on_missing_optional` | 枚举 | `SKIP_WITH_LIMITATION` 等稳定行为 |
| 降级 | `on_budget_exhausted` | 枚举 | 必须能表达「不做部分抽样」 |
| 幂等 | `idempotency_keys` | 字段路径集合 | 至少覆盖 `request_id` |
| 幂等 | `side_effects` | 集合 | **v1 必须为空**，即只读；写副作用需单独 ADR 审查 |
| 观测 | `audit_codes` | 稳定码集合 | 供 Guardrail 与日志断言 |
| 观测 | `stable_error_codes` | 稳定码集合 | 避免错误码散落在实现里 |

### 3.1 硬规则

1. **编译期注册。** Manifest 是 Python 声明的一等对象；禁止在运行时从磁盘、网络或用户输入加载（对齐架构 §2.3）。
2. **启动 fail-fast。** manifest 中的 Capability、Toolset、`DomainOperation` 名必须在启动时逐项对 Capability Registry 校验；任一不存在则启动失败，不允许运行时静默跳过。
3. **不得泄露实现细节。** manifest 中禁止出现供应商名、MCP tool 名、URL、传输协议或凭证。
4. **不得成为第二真源。** manifest 声明「需要哪些能力」，Capability Registry 仍是「有哪些能力」的唯一真源；两者冲突时以 Registry 为准并使启动失败。
5. **候选集公式不变。** Planner 最终候选集仍为 `Requirement Policy ∩ Toolset ∩ Authorization Policy`；manifest 只用于声明与校验，不参与运行时放宽。

## 4. `DomainDescriptor` 字段表（冻结）

| 字段 | 说明 |
|---|---|
| `domain` | 稳定小写标识，如 `finance` |
| `descriptor_version` | 描述版本 |
| `status` | 复用架构 §0.2 状态标记 |
| `supported_intents` | 该域声明可处理的意图集合 |
| `enabled_intents` | 当前实际启用的子集；未启用的意图必须返回 `ACTION_NOT_ENABLED` |
| `skills` | 该域下的 `SkillManifest` 列表 |
| `request_contract` | 该域的请求契约模型名 |
| `outcome_contract` | 该域的结果契约模型名 |

Dispatcher 通过 descriptor 完成路由与拒绝，因此**不需要 import 任何领域枚举**，ADR-009 §3.3 的内核纯净度得以保持。

## 5. Dispatcher 行为（冻结）

| 情况 | 行为 |
|---|---|
| `domain` 未注册 | 返回稳定失败，错误码 `DOMAIN_NOT_REGISTERED`；不抛未处理异常 |
| `domain` 已注册但意图不在 `enabled_intents` | 返回 `FAILED + ACTION_NOT_ENABLED`，不静默降级为其他意图 |
| 意图已启用但无 Skill 声明 `accepted_intents` 包含它 | 启动时即失败（配置错误），不留到运行时 |
| 同一 domain 重复注册 | 保持现有 `DomainRegistry` 行为：直接报错，禁止静默覆盖 |

## 6. 实施边界

- 落地方式为一个独立代码切片：`DomainRegistry` 升级为携带 descriptor 的 Dispatcher + 为 `finance` 补一份 descriptor 与三份 manifest（声明现状）；
- 该切片必须**零对外行为变更**，验收包含全量回归通过与内核纯净度测试常绿；
- 时点排在当前 M3 切片交付之后、M4 开始之前，不得插队；
- 回滚方式为移除 descriptor / manifest 注册与校验调用。

### 6.1 执行记录（2026-08-11 已落地）

切片已执行，零对外行为变更，全量回归通过。落地清单：

| 交付物 | 位置 | 说明 |
|---|---|---|
| 通用 manifest 模型 | `domains/manifests.py` | `SkillManifest`（24 字段）+ `DomainDescriptor`（8 字段），只依赖 `domains.contracts`，保持内核纯净 |
| Finance descriptor + 3 manifest | `domains/finance/manifests.py` | `stock-research`(CURRENT) / `portfolio-health`(FOUNDATION) / `suitability-evaluation`(FOUNDATION)；能力名从 `authorization.py` 派生，防双源漂移 |
| DomainRegistry 升级 | `domains/registry.py` | 新增 `register_descriptor` / `descriptor` / `is_intent_enabled`；现有 `register/get/contains/list_domains` 签名与行为不变 |
| 启动 fail-fast 校验 | `runtime/manifest_validation.py` + `application.py` 4.6c | 校验 capability 存在性、toolset 合法性、`side_effects` 为空、enabled intent 有 Skill 声明；任一不一致 → `ConfigurationError` |
| M3 能力补注册 | `tools/capabilities.py` | `portfolio.build_current_valuation`（确定性重算，adapter=local）补入 Registry，消除「Builder 产出但 Registry 不可见」的隐患 |
| 契约回归测试 | `tests/contracts/test_manifests.py` | 防漂移：manifest 能力 = 授权映射并集；authority_field 指向真实 Outcome 字段；v1 只读；descriptor 注册边界 |
| 架构门禁测试 | `tests/architecture/test_manifest_validation.py` | 启动校验通过 + 四类 fail-fast；`domains/manifests.py` 纯净度扩展（不 import finance/tools/integrations） |

三份 manifest 的 `status` 严格声明现状：只有 `stock-research` 端到端跑通（`CURRENT`），另外两个被 `runtime.py:124` 的 `ACTION_NOT_ENABLED` 门拦住（`FOUNDATION`）；`enabled_intents = {STOCK_RESEARCH}` 与运行时行为完全一致。

## 7. 后果

正面：manifest 与 Registry 的一致性由启动校验保证；新增 Skill 的合规检查从人工评审变为机器校验；`authority_field` 让 M2 式双源问题在契约层可见。

代价：Skill 增加一处声明，改动 Skill 时需同步 manifest；启动 fail-fast 会把原本延迟到运行时的配置错误提前暴露为启动失败，这是有意的选择。
