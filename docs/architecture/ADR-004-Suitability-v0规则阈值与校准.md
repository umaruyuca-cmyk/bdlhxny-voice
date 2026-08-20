# ADR-004：Suitability v0 规则阈值与校准

> 状态：DRAFT_IN_RUNTIME（规则以代码 `suitability-v0.1` + `status=DRAFT` 运行；不再用「未签署禁止写 Engine」挡开发）
> 说明：数值是内部启发式，可改；对外须标明「风险匹配筛查」，不是法定适当性。历史 NOT_APPROVED 签署流程已降级。
> 日期：2026-08-10（草案）；运行时启用：2026-08-17
> 审核角色：产品/工程可直接改阈值并 PR；如需对外合规声明再另开审批

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
3. `ResearchRisk.severity` 只用于向更严档提升：存在 `CRITICAL`/`HIGH`→`HIGH`；
   否则存在 `MEDIUM`→至少 `MEDIUM`。仅有 LOW 或没有风险条目不能证明 LOW；若
   MDD/vol 也不可用则不输出 band。

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
| 等号 | `== needs` → CONDITIONAL；`== needs*1.20` → PASS |
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

## 7. 初审记录（2026-08-12）

### 7.1 结论

**CHANGES_REQUIRED，不批准 `suitability-v0.1-draft`。** 当前应继续保持
`NOT_APPROVED` 和 fail-closed 前置行为，不得装配为生产规则集。本次为工程与规则一致性
初审，不替代业务、风险或合规负责人的最终批准。

官方适当性规则要求经营机构全面了解投资者情况，对产品或服务进行科学有效的风险分级，
形成明确匹配意见，并建立依据、方法、流程、更新和留痕机制；并未给出本文的 15%/20%、
20%/40% 或 1.20 倍等数值。因此这些数值只能作为待验证的内部政策参数，不能表述为法规
阈值，也不能仅凭“偏保守常识”批准。

### 7.2 问题与整改状态

| 严重性 | 问题 | 审核要求 |
|---|---|---|
| DONE | §6.6 的 `liquid_assets == needs` 边界曾自相矛盾。 | 已按推荐文档统一为 CONDITIONAL；`needs == 0` 等校准边界仍须在测试集冻结。 |
| P0 | Java 已采集 `near_term_cash_needs_horizon_days`，但原 Python 契约曾丢弃该字段，“近期”没有可审计期限。 | 字段已贯通；仍须冻结 horizon 适用范围，超过范围或缺失时 UNKNOWN。 |
| P0 | §6.0/§6.8 允许“已确认拟投入金额或配置比例”后输出 `SUITABLE`，但当前 `FinancialDomainRequest`、Snapshot 和受控确认链路都没有该输入。§6.9 的对应样本当前不可执行。 | v0 二选一：删除 `SUITABLE` 可达分支并始终封顶，或先增加服务端确认的拟配置契约及买入后集中度计算。 |
| DONE | §6.2 所需确认元数据原先没有结构化保留。 | 已增加 `FinancialDataReference` 并校验版本一致性；具体 freshness 阈值仍待冻结。 |
| DONE | §6.0.1 原先把“仅 LOW 或没有 `ResearchRisk`”推成 LOW。 | 已删除该推断；无客观输入时契约强制使用 UNKNOWN。 |
| P0 | `asset_risk_band` 目前实质是历史 MDD/波动率代理，未冻结回看窗口、最少样本、复权口径、停牌/新股行为和数据质量；也未覆盖流动性、杠杆、复杂性、信用、跨境等产品风险因素。 | 将其明确命名为内部“市场风险代理带”，补齐方法学；若对外称产品/服务风险等级，须增加完整分级因子与适用性审查。 |
| P0 | 数值阈值没有政策依据、历史样本或误判成本分析，§6.9 只有示例用例，不能证明分档有效。 | 提交校准报告：样本范围/时间、分层、边界样本、假阳性/假阴性、敏感性分析、回测限制、漂移监控和变更审批。 |
| P0 | 当前输出名包含 `SUITABLE`，但输入远少于正式适当性所要求的投资者信息与产品风险因子，容易被理解为完整适当性结论。 | 产品/合规确认法律定位；v0 对外统一称“风险匹配筛查结果”，禁止宣称完成法定适当性评估。 |
| P1 | §4.1 建议 ETF/基金缺少独立分级时沿用股票 band，产品结构与风险因素不同。 | v0 先限定普通 A 股现货；ETF、基金、杠杆/反向产品、两融、衍生品、跨境品种另行 ADR。 |
| P1 | §6.5 当前行业集中度依赖用户维护的 `sector`，但未定义行业分类版本、同义映射、缺字段以及分类变更行为。 | 冻结分类体系和版本；任一有效持仓缺行业时该子规则 UNKNOWN，并明确是否为关键。 |
| P1 | §6.8 先聚合关键 UNKNOWN，可能遮蔽同轮已确定的 BLOCK。 | 总结果可保持 INSUFFICIENT，但响应必须同时保留已证实的冲突和证据，不能显示为无风险。 |
| P1 | 风险画像和市场数据未规定有效期，用户信息或标的状态变化后仍可能复用旧结论。 | 为风险画像、持仓、流动性、行情和研究分别冻结 freshness；过期即 UNKNOWN，并定义重新确认流程。 |

### 7.3 非阻塞认可项

- fail-closed、MOCK/UNAVAILABLE 不参与生产个性化、缺关键数据不猜测的方向正确；
- 回撤和波动率统一转换为百分数点、禁止隐式换汇、理由携带 evidence refs 的方向正确；
- 历史回撤不表述为未来损失承诺、禁止交易指令和收益承诺的文案边界正确；
- 无拟投入金额时不得按买入后集中度得出肯定性结果的产品封顶方向正确。

### 7.4 复审最小交付物

1. 修订后的规则表（含全部等号、零值、缺数、过期和币种边界）；
2. `asset_risk_band` 方法学与明确的 v0 适用/排除资产清单；
3. Snapshot 确认元数据、流动性 horizon、拟配置输入的契约决定；
4. 阈值校准报告和机器可执行的边界测试集；
5. 业务/风险/合规负责人在 §4.1 的实名或可追溯审批记录。

### 7.5 初审依据

- 中国证监会《证券期货投资者适当性管理办法》：重点参照第三、六、十三、十五至十八、
  二十一至二十五、二十九、三十二条；
- 中国证券业协会《证券经营机构投资者适当性管理实施指引（试行）》及发布答记者问：
  重点参照风险揭示、匹配意见、内部控制、回访和资料保存要求；
- 本仓库 `FinancialDomainRequest`、`FinancialSnapshot`、`LiquiditySnapshot`、
  `PortfolioPositionsResponse`、`JavaDataQueryService` 及确定性风险指标实现。

### 7.6 Python 契约整改进度（2026-08-12）

已根据《Suitability v0 固定规则 · 推荐文档》完成契约层整改，但不代表阈值获批：

- 已增加 `FinancialDataReference`，保留 capability、observation、data mode、数据时间、
  查询时间、服务端确认引用和 profile version；
- 已为 `LiquiditySnapshot` 贯通币种、近期资金需求 horizon 和来源；缺失时保持 UNKNOWN；
- 已增加 `MarketRiskProxy`，明确它是历史市场风险代理，并禁止无客观输入推导 LOW；
- 已增加 `SuitabilityRuleEvaluation`，固定七条 Rule ID 和
  `PASS / CONDITIONAL / BLOCK / UNKNOWN`，保留实际值、阈值、理由和证据；
- 已增加 `SuitabilityV0RuleSet`，强类型表达风险带、集中度、流动性和等号边界；未批准
  实例不得携带审批元数据，批准实例不得使用 `-draft` 版本；
- `SuitabilityAssessment` 对外定位为 `PERSONALIZED_RISK_MATCHING_SCREEN`；当前没有受控
  拟配置输入时，契约禁止构造 `SUITABLE`；
- Snapshot Builder 已保留目标期限和金额，不再在复制确认目标时丢弃字段；
- Python 全量回归通过。生产规则集仍未装配，继续 fail-closed。

---

## 8. 审核清单（整改后复审时勾选）

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

## 9. 后果

- **本次初审：** 已形成修改清单，但未替业务/风险/合规负责人选择阈值或签署。
- **未签前：** 保持现有 `SuitabilityPreflight` 行为，不产出三类个性化结论。
