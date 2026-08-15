# ADR-004：Suitability v0 规则阈值与校准

> 状态：PROPOSED / NOT_APPROVED
> 阻塞：M3 production SuitabilityEngine
> 日期：2026-08-10

## 1. 决策目标

冻结 Suitability v0 的 Rule ID、输入、单位、阈值、等号边界、缺数行为、公开理由和
聚合优先级。本文在获得业务/风险负责人批准前不得作为生产阈值来源。

## 2. 已确定的非数值规则

- 输入仅为同轮 COMPLETE `StockResearchResult` 与 LIVE/受控 USER_CONFIRMED Snapshot；
- `*_pct` 与 exposure 使用百分数点 `0..100`；金额保留 currency，不暗自跨币种换算；
- 单规则输出 `PASS / CONDITIONAL / BLOCK / UNKNOWN`；
- 聚合：关键 UNKNOWN → INSUFFICIENT；否则 BLOCK → CURRENTLY_NOT_SUITABLE；否则
  CONDITIONAL → CONDITIONALLY_SUITABLE；全部必需规则 PASS → SUITABLE；
- Rule reason 使用批准模板，必须携带 evidence refs；不生成交易指令。

## 3. 待批准规则表

| Rule ID（提案） | 输入 | 阈值/边界 | 缺数行为 | 状态 |
|---|---|---|---|---|
| `SUIT-RESEARCH-COVERAGE-001` | research coverage/confidence | COMPLETE 门禁 | INSUFFICIENT | 待批准 |
| `SUIT-DATA-AUTHENTICITY-001` | data_mode/completeness | LIVE/受控确认门禁 | INSUFFICIENT | 待批准 |
| `SUIT-RISK-LEVEL-001` | risk_level + asset risk | `TBD_APPROVAL` | UNKNOWN（关键） | 未批准 |
| `SUIT-MAX-LOSS-001` | max_loss_tolerance_pct + drawdown | `TBD_APPROVAL` | UNKNOWN（关键） | 未批准 |
| `SUIT-CONCENTRATION-001` | current single/industry exposure | `TBD_APPROVAL` | UNKNOWN（关键） | 未批准 |
| `SUIT-LIQUIDITY-001` | liquid_assets/near_term_cash_needs | `TBD_APPROVAL` | UNKNOWN（关键） | 未批准 |
| `SUIT-GOAL-HORIZON-001` | confirmed goal horizon + asset risk | `TBD_APPROVAL` | UNKNOWN（非关键） | 未批准 |

## 4. 审批要求

批准人必须确认每个阈值、等于阈值的分支、适用市场/资产范围、校准样本、版本号和公开
理由模板。批准后将状态改为 APPROVED 并记录签署信息；代码只接受 APPROVED 版本，
禁止在运行时回退到本文的 `TBD_APPROVAL`。
