# ADR-004：Suitability v0 规则阈值与校准

> 状态：PROPOSED / NOT_APPROVED（含 **推荐草案 `suitability-v0.1-draft`，待审核人签署**）
> 阻塞：M3 production SuitabilityEngine 开放三类个性化结论
> 日期：2026-08-10
> 草案日期：2026-08-11
> 审核角色：业务 / 风险 / 合规负责人（当前可由产品负责人兼审；**开发实现者不可自批后直接当生产阈值**）

## 1. 决策目标

冻结 Suitability v0 的 Rule ID、输入、单位、阈值、等号边界、缺数行为、公开理由和
聚合优先级。本文在获得业务/风险负责人批准前不得作为生产阈值来源。

**你现在要做的事：** 审阅下方 §6「推荐草案」，勾选通过或改数字；签署后把状态改为
`APPROVED`，`rule_set_version` 去掉 `-draft` 后缀，代码才允许装配该版本。

## 2. 已确定的非数值规则（沿用，不因草案改变）

- 输入仅为同轮 COMPLETE `StockResearchResult` 与 LIVE/受控 USER_CONFIRMED Snapshot；
- `*_pct` 与 exposure 使用百分数点 `0..100`；金额保留 currency，不暗自跨币种换算；
- 单规则输出 `PASS / CONDITIONAL / BLOCK / UNKNOWN`；
- 聚合：关键 UNKNOWN → `INSUFFICIENT_INFORMATION`；否则任一 BLOCK →
  `CURRENTLY_NOT_SUITABLE`；否则任一 CONDITIONAL → `CONDITIONALLY_SUITABLE`；
  全部必需规则 PASS → 才可能 `SUITABLE`（另受 §6.0 产品封顶约束）；
- Rule reason 使用批准模板，必须携带 evidence refs；不生成交易指令。

## 3. 待批准规则表（摘要；细节见 §6）

| Rule ID | 输入 | 阈值/边界（草案） | 缺数行为 | 状态 |
|---|---|---|---|---|
| `SUIT-RESEARCH-COVERAGE-001` | research coverage/confidence | 须 `COMPLETE` 且 confidence ≥ `MEDIUM` | 关键 → INSUFFICIENT | 待审 |
| `SUIT-DATA-AUTHENTICITY-001` | data_mode/completeness | `LIVE` 或带 `confirmation_ref` 的 `USER_CONFIRMED` | 关键 → INSUFFICIENT | 待审 |
| `SUIT-RISK-LEVEL-001` | risk_level + asset_risk_band | 见 §6.3 匹配矩阵 | UNKNOWN（关键） | 待审 |
| `SUIT-MAX-LOSS-001` | max_loss_tolerance_pct + \|MDD\| | `\|MDD\| > 容忍` → BLOCK；`=` → CONDITIONAL | UNKNOWN（关键） | 待审 |
| `SUIT-CONCENTRATION-001` | 当前单标的/行业 weight_pct | 见 §6.5 分档阈值 | UNKNOWN（关键） | 待审 |
| `SUIT-LIQUIDITY-001` | liquid_assets / near_term_cash_needs | 见 §6.6 | UNKNOWN（关键） | 待审 |
| `SUIT-GOAL-HORIZON-001` | confirmed goal horizon + asset_risk_band | 见 §6.7 | UNKNOWN（**非**关键） | 待审 |

## 4. 审批要求

批准人必须确认每个阈值、等于阈值的分支、适用市场/资产范围、校准样本、版本号和公开
理由模板。批准后将状态改为 APPROVED 并记录签署信息；代码只接受 APPROVED 版本，
禁止在运行时回退到 `TBD_APPROVAL` 或未签署的 `-draft`。

### 4.1 签署栏（审核通过后填写）

| 项 | 填写 |
|---|---|
| 规则集版本 | `suitability-v0.1`（批准后去掉 draft） |
| 适用市场/资产 | 建议：A 股股票为主；ETF/基金若无独立分级则沿用同一 `asset_risk_band` |
| 审核人姓名/角色 | |
| 签署日期 | |
| 意见 | 全盘通过 / 附修改清单后通过 |

## 5. 延期决策与开发边界（2026-08-11 记录）

### 5.1 决策状态

阈值正式批准可与 M3 代码基础并行准备；**未批准前**不阻塞契约、Snapshot、估值、
fail-closed 前置与测试，但阻塞默认流量中的个性化三类结论。

### 5.2 拟采用的 v0 产品边界

在缺少「拟投入金额 / 拟配置比例」时，系统不能可靠计算买入后集中度，也不得把单标的
分析描述为「适合购买」。首个面向用户能力定位为**风险匹配筛查（非投资建议）**：

- 数据不足 → `INSUFFICIENT_INFORMATION`；
- 已批准硬冲突 → `CURRENTLY_NOT_SUITABLE` + 证据；
- 数据齐但无拟投入金额/配置比例 → **不得输出 `SUITABLE`**（草案封顶为
  `CONDITIONALLY_SUITABLE` + 待确认条件）；
- 禁止买卖、仓位、调仓或收益承诺语义。

### 5.3 不可放宽的安全约束

`NOT_APPROVED` 时不得用示例阈值生成生产三类个性化结论；规则装配失败关闭。

---

## 6. 推荐草案 `suitability-v0.1-draft`（供审核）

> **性质：** 工程侧基于 Prompt §10.4、现有 Snapshot/Research 字段和偏保守的零售风控
> 常识给出的**建议值**，不是已生效标准。  
> **审核人可改任何数字**；改完再签。未签前代码仍走 Preflight → 仅
> `INSUFFICIENT_INFORMATION`。

### 6.0 全局约定

| 项 | 推荐 |
|---|---|
| `rule_set_version`（草案） | `suitability-v0.1-draft` |
| `rule_set_version`（批准后） | `suitability-v0.1` |
| 百分数单位 | 一律百分数点 `0..100`（例：回撤 25% 写作 `25`，不是 `0.25`） |
| 金额 | 与 Snapshot 同币种；禁止暗换汇 |
| `projected_exposure` | **v0 不启用**（必须为空）；只评 `current_exposure` |
| 标的风险带 `asset_risk_band` | 见 §6.0.1；无法则风险/回撤相关规则打关键 UNKNOWN |
| 最终 `SUITABLE` 封顶 | 即使七条皆 PASS，若用户未提供**已确认的拟投入金额或拟配置比例**，结果封顶为 `CONDITIONALLY_SUITABLE`，并加入 `required_conditions`：`SUITABILITY_PROPOSED_AMOUNT_REQUIRED` |

#### 6.0.1 标的风险带推导（v0 可审计方法）

输入优先序（取得到的最严一档）：

1. 研究侧已标准化的 `asset_risk_band`（若未来字段存在）；
2. 否则用同轮 technical/risk 计算：`max_drawdown_pct = abs(MDD) * 100`（若引擎给的是比例则换算为百分数点）、`vol_ann_pct`（年化波动百分数点）；
3. 否则用 `ResearchRisk.severity`：存在 `CRITICAL`→`HIGH`；否则存在 `HIGH`→`HIGH`；否则存在 `MEDIUM`→`MEDIUM`；仅 `LOW` 或无风险条目→`LOW`。

分档（等号归入更严档，即 `>=`）：

| `asset_risk_band` | 条件（满足任一） |
|---|---|
| `HIGH` | `max_drawdown_pct >= 40` **或** `vol_ann_pct >= 35` **或** severity 推导为 HIGH |
| `MEDIUM` | `max_drawdown_pct >= 20` **或** `vol_ann_pct >= 20` **或** severity 推导为 MEDIUM |
| `LOW` | 其余可计算情形 |
| （不可用） | MDD/vol/severity 皆不可用 → 不输出 band，相关规则 UNKNOWN |

### 6.1 `SUIT-RESEARCH-COVERAGE-001`（研究门禁，关键）

| 项 | 推荐 |
|---|---|
| 输入 | `StockResearchResult.coverage`、`confidence.level` |
| PASS | `coverage == COMPLETE` **且** `confidence.level ∈ {MEDIUM, HIGH}` |
| BLOCK | 不使用（门禁失败走缺数/不足，不直接 NOT_SUITABLE） |
| 缺数/不满足 | 视为关键失败 → 聚合为 `INSUFFICIENT_INFORMATION`（实现上可映射为关键 UNKNOWN 或前置硬门禁，与 Prompt §10.4.5 一致） |
| 等号 | `MEDIUM` 含在内（`>= MEDIUM`） |
| 公开理由模板 | `研究覆盖或置信度不足，无法做个性化匹配。coverage={coverage}, confidence={confidence}` |

### 6.2 `SUIT-DATA-AUTHENTICITY-001`（真实性门禁，关键）

| 项 | 推荐 |
|---|---|
| 输入 | `FinancialSnapshot.data_mode`、`is_mock`、关键字段完整性、`confirmation_ref`/provenance |
| PASS | `data_mode == LIVE`，或 `data_mode == USER_CONFIRMED` 且带服务端确认引用；且非 mock；且风险/持仓估值等本规则集所需关键字段齐全 |
| 不满足 | `INSUFFICIENT_INFORMATION`（MOCK / UNAVAILABLE / 生产态 TEST_FIXTURE 一律不足） |
| 公开理由模板 | `用户金融数据真实性或完整性不满足适配评估要求。data_mode={data_mode}` |

### 6.3 `SUIT-RISK-LEVEL-001`（风险等级匹配，关键）

| 项 | 推荐 |
|---|---|
| 输入 | `risk_profile.risk_level`、`asset_risk_band` |
| 缺 `risk_level` 或 band | UNKNOWN（关键）→ `INSUFFICIENT_INFORMATION` |

**匹配矩阵（推荐）：**

| 用户 `risk_level` | PASS | CONDITIONAL | BLOCK |
|---|---|---|---|
| `CONSERVATIVE` | `LOW` | — | `MEDIUM`、`HIGH` |
| `BALANCED` | `LOW`、`MEDIUM` | — | `HIGH` |
| `AGGRESSIVE` | `LOW`、`MEDIUM`、`HIGH` | — | — |

| 公开理由（BLOCK） | `标的风险带与您的风险承受等级不匹配。您的等级为 {risk_level}，标的风险带为 {asset_risk_band}。` |
| 公开理由（PASS） | 可不展示，或简短：`风险等级与标的风险带匹配。` |

### 6.4 `SUIT-MAX-LOSS-001`（最大损失容忍，关键）

| 项 | 推荐 |
|---|---|
| 输入 | `max_loss_tolerance_pct`（0..100）、研究 `max_drawdown_pct`（0..100，绝对值） |
| PASS | `max_drawdown_pct < max_loss_tolerance_pct` |
| CONDITIONAL | `max_drawdown_pct == max_loss_tolerance_pct`（压线） |
| BLOCK | `max_drawdown_pct > max_loss_tolerance_pct` |
| 缺任一 | UNKNOWN（关键） |
| 公开理由（BLOCK） | `标的历史最大回撤 {max_drawdown_pct}% 超过您设定的最大损失容忍 {max_loss_tolerance_pct}%。` |
| 公开理由（CONDITIONAL） | `标的历史最大回撤恰好达到您的最大损失容忍 {max_loss_tolerance_pct}%，请确认是否可接受。` |

说明：历史 MDD 不是对未来损失的承诺，理由中不得写成「一定会亏」或「保证不亏」。

### 6.5 `SUIT-CONCENTRATION-001`（当前集中度，关键）

只使用**当前**持仓权重；无该标的持仓时单标的权重视为 `0`（PASS 集中度，不表示适合买入）。

**单标的 `weight_pct`（当前）：**

| 用户 risk_level | CONDITIONAL（`>`） | BLOCK（`>`） |
|---|---|---|
| `CONSERVATIVE` | 15 | 20 |
| `BALANCED` | 20 | 30 |
| `AGGRESSIVE` | 30 | 40 |

等号：`weight == 阈值` 归入**不含**该档（即用严格 `>`）；`weight == 20` 对保守型不算 BLOCK。  
若你希望「等于也算超标」，审核时改为 `>=`。

**行业暴露 `industry_weight_pct`（当前，可算时）：**

| 用户 risk_level | CONDITIONAL（`>`） | BLOCK（`>`） |
|---|---|---|
| `CONSERVATIVE` | 30 | 40 |
| `BALANCED` | 40 | 50 |
| `AGGRESSIVE` | 50 | 60 |

| 缺估值/权重无法算集中度 | UNKNOWN（关键） |
| 公开理由（BLOCK） | `当前单标的或行业集中度过高。类型={exposure_type}，当前={current_value}%，阈值={threshold}%。` |

### 6.6 `SUIT-LIQUIDITY-001`（流动性，关键）

| 项 | 推荐 |
|---|---|
| 输入 | `liquid_assets`、`near_term_cash_needs`（同币种） |
| PASS | `liquid_assets >= near_term_cash_needs * 1.20` |
| CONDITIONAL | `near_term_cash_needs <= liquid_assets < near_term_cash_needs * 1.20` |
| BLOCK | `liquid_assets < near_term_cash_needs` |
| 等号 | `== needs` → BLOCK（无缓冲）；`== needs*1.20` → PASS |
| 缺任一关键字段 | UNKNOWN（关键） |
| 公开理由（BLOCK） | `可变现资产不足以覆盖近期资金需求。` |
| 公开理由（CONDITIONAL） | `可变现资产对近期资金需求的缓冲不足 20%，请确认短期开支安排。` |

### 6.7 `SUIT-GOAL-HORIZON-001`（目标期限，非关键）

| 项 | 推荐 |
|---|---|
| 输入 | 已确认 goals 的 `horizon` + `asset_risk_band` |
| goals 为空 | UNKNOWN（**非关键**）：不单独导致 INSUFFICIENT，也不得单独促成 SUITABLE |
| BLOCK | 存在 `horizon == SHORT_TERM` 且 `asset_risk_band == HIGH` |
| CONDITIONAL | 存在 `SHORT_TERM` 且 `MEDIUM`；或 `MEDIUM_TERM` 且 `HIGH` |
| PASS | 其余有目标且可比较的情形 |
| 公开理由（BLOCK） | `存在短期目标，但标的风险带为高，期限与风险不匹配。` |

### 6.8 聚合优先级（冻结）

按规则输出后：

```text
1. 任一「关键」规则为 UNKNOWN           → INSUFFICIENT_INFORMATION
2. 否则任一规则为 BLOCK                 → CURRENTLY_NOT_SUITABLE
3. 否则任一规则为 CONDITIONAL           → CONDITIONALLY_SUITABLE
4. 否则全部必需规则 PASS：
     - 已确认拟投入金额或配置比例     → SUITABLE
     - 否则                           → CONDITIONALLY_SUITABLE
       + required_condition: SUITABILITY_PROPOSED_AMOUNT_REQUIRED
```

硬门禁（研究未 COMPLETE、MOCK 快照等）在进 Engine 前按 Prompt §10.4.5 处理，不进入「假装 PASS」。

### 6.9 校准样本（建议审核时至少过一遍）

| 场景 | 期望结果 |
|---|---|
| research PARTIAL | INSUFFICIENT |
| Snapshot MOCK | INSUFFICIENT |
| 保守用户 + asset HIGH | CURRENTLY_NOT_SUITABLE（风险规则 BLOCK） |
| 平衡用户 + MDD 30 + 容忍 20 | CURRENTLY_NOT_SUITABLE（损失规则 BLOCK） |
| 平衡用户 + MDD 20 + 容忍 20 | CONDITIONALLY_SUITABLE（压线） |
| 进取用户 + 全 PASS + 无拟投入金额 | CONDITIONALLY_SUITABLE（封顶） |
| 进取用户 + 全 PASS + 已确认拟投入金额 | SUITABLE |
| 无 goals，其余 PASS | 不因目标 UNKNOWN 变 INSUFFICIENT |

---

## 7. 审核清单（请直接勾）

- [ ] §6.0.1 标的风险带分档（20/40 回撤、20/35 波动）可接受，或给出替代数字  
- [ ] §6.3 风险匹配矩阵可接受  
- [ ] §6.4 最大损失：`>` BLOCK、`=` CONDITIONAL 可接受  
- [ ] §6.5 集中度分档与「严格 `>`」可接受  
- [ ] §6.6 流动性 1.20 缓冲可接受  
- [ ] §6.7 目标规则非关键可接受  
- [ ] §6.0 / §6.8「无拟投入金额不得 SUITABLE」可接受  
- [ ] 公开理由模板无交易指令、无收益承诺  
- [ ] 适用市场范围确认（默认 A 股股票）  
- [ ] 签署 §4.1 并改状态为 `APPROVED`，版本改为 `suitability-v0.1`

## 8. 后果

- **你只审、不改代码：** 回复哪些阈值要改即可，签署后我再把 ADR 标成 APPROVED，并让实现只加载该版本。  
- **未签前：** 保持现有 `SuitabilityPreflight` 行为，不产出三类个性化结论。
