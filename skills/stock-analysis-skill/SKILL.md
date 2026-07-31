---
name: stock-analysis-skill
description: A 股/ETF/场外基金投资分析 Skill，使用北京时间数据校验、确定性技术计算、ETF多周期动量轮动、波动率目标仓位和无未来函数历史回测。用于 A股分析、场内ETF、ETF池轮动、量化回测、场外ETF联接、QDII、持仓分析、追高判断、补仓时机、月度资金分配、/stock-analysis、/持仓分析 或 /板块轮动；调用内置 npm CLI 获取并核验行情/净值，输出中文决策看板，不接受用户未经核实的市场判断。
---

# A-Share / ETF / Fund Analysis Skill

Use this skill to analyze A-share stocks, exchange-traded ETFs, OTC ETF-linked funds, QDII funds, sector rotation, and portfolio risk using a single objective analysis standard. There is no conservative/balanced/aggressive profile selection — all judgments are based on the same technical-indicator facts and the same thresholds. Hard chase-high warnings and confirmed downtrends always block new buys regardless of any user preference.

## Fact Verification Discipline (核心纪律)

**Never accept the user's stated facts as truth without independent verification.** Always fetch or compute the actual data before stating any factual claim about price, moving averages, support/resistance, volume, or indicator values.

This applies especially to:

- **MA / support breaks**: when the user says "破 MA20", "破 30 日线", "跌穿支撑", do NOT repeat it — run the skill CLI or fetch the K-line and compute the actual MA value and deviation first. State whether the level is genuinely broken (close below), merely being tested (price touching/above), or still holding.
- **Chase-high / washout / distribution labels**: do not echo the user's "在洗盘", "主力出货", "资金很强" framing. Apply the objective labels from `Trend And Fund-Flow Quality` based on the computed indicators, and correct the user when their framing diverges from the data.
- **Volume characterization**: "放量/缩量" must come from the volume ratio or day-over-day volume comparison, not from the user's feeling. Note that intraday volume ratios need time-scaling (see the 量比 fix in `src/analysis/technical.js`).
- **Relative strength**: when the user claims "X 跌得最少" or "X 最强", pull the comparison basket and rank by actual change before agreeing.

If the user's stated fact turns out to be wrong, correct it explicitly with the numbers — do not soften or go along with it to avoid friction. Trading decisions made on an unverified premise (e.g., acting as if MA30 is broken when price is actually sitting on it) lead to wrong risk sizing. Independence of judgment is part of the objective standard.

## Data Freshness Discipline（时效硬约束）

- A 股市场时间一律使用 `Asia/Shanghai`，不得使用宿主电脑本地时区推断“今天”。
- 在引用价格或技术指标前，必须读取 CLI 输出的 `数据截至`、`行情时间`、`数据可信度`、`最新K线/净值`。
- “接口返回成功”不等于“实时”。只有 `dataQuality.status=live` 才能称为盘中实时行情。
- `delayed`、`stale`、`unknown` 或盘中最新K线不是北京时间当天时，方向性信号由 CLI 强制降为 `观望`，不得恢复成买入、加仓或卖出建议。
- `previous_close` 只能称为最近收盘数据，不得称为今日实时行情。
- 场外基金、ETF 联接和 QDII 只能称为“最新已公布净值”；必须说明净值日期和滞后交易日数，不得使用“现价/实时净值”。
- 盘中合成K线产生的 MA、RSI、MACD 和量比均为临时值，必须明确标注，收盘后需要重新计算。
- 交易状态必须同时通过北京时间和交易所休市日历校验；日历年份未覆盖时必须披露“未完全核验”。

## Quick Start

Run the versioned NPM CLI from this skill folder or from an installed package:

```bash
npm install
node bin/stock-analysis.js --help
node bin/stock-analysis.js sector
node bin/stock-analysis.js stock 159801 --asset etf
node bin/stock-analysis.js --no-save stock 588200 --asset etf --json
node bin/stock-analysis.js stock 022463 --asset open_fund
node bin/stock-analysis.js stock 017641 --asset qdii
node bin/stock-analysis.js portfolio --config templates/portfolio.example.json
node bin/stock-analysis.js quant 510300 159915 512100 --benchmark 510300
npm pack
npm install /path/to/stockwise-stock-analysis-skill-1.1.1.tgz
```

If `portfolio.json` is absent, the CLI uses `templates/portfolio.example.json` and prints a warning. A real user portfolio should be the single source of truth for holdings and monthly budget.

### JSON Contract

Backend integrations must add `--json` to `stock`, `portfolio`, `quant`, and `sector`. Read [references/json-contract.md](references/json-contract.md) before implementing or changing a machine consumer. The Skill itself owns serialization; never ask a wrapper or model to infer fields from the Chinese terminal board.

Before explaining or changing an analysis rule, read [references/methodology.md](references/methodology.md). Distinguish deterministic calculations, research-based model direction, risk policy, and uncalibrated heuristics. Never present the 100-point score, sector heat score, adding ladder, or position thresholds as statistically proven expected returns.

Use `stock <code> --json` when a backend service needs deterministic report data. The CLI writes exactly one UTF-8 JSON document to standard output; data-source retries and diagnostic messages use standard error. Programs must parse standard output only and retain standard error for logs.

The top-level contract is versioned:

```json
{
  "schemaVersion": "1.1",
  "command": "stock",
  "timezone": "Asia/Shanghai",
  "asOf": "2026-07-27 09:32:34",
  "request": {
    "code": "588200",
    "asset": "etf",
    "days": 120
  },
  "profile": {},
  "data": {
    "code": "588200",
    "name": "科创芯片ETF嘉实",
    "quote": {},
    "history": [],
    "technical": {},
    "score": {},
    "chase": {},
    "fundamental": {},
    "dataQuality": {},
    "sources": {},
    "assetKind": "exchange_traded"
  },
  "trading": {
    "session": {},
    "lotTrade": {},
    "positionRisk": null
  }
}
```

`asOf` is the verified market-data time in Beijing time, not the model response time. Always inspect `data.dataQuality.status`, `allowsDirectionalSignal`, `provisional`, and `warnings` before assembling a directional conclusion. Consumers should reject unsupported `schemaVersion` values instead of silently guessing field meanings. `data.history` and `data.technical.series` provide the deterministic chart data and are limited by `--days`.

## Portfolio Config

Use this shape:

```json
{
  "monthlyBudget": 5000,
  "cash": 0,
  "tradingCosts": {
    "commissionRate": 0.0003,
    "minCommission": 5,
    "stampDutyRate": 0.0005,
    "transferFeeRate": 0.00001,
    "lotSize": 100,
    "minTradeAmount": 1500,
    "preferredTradeAmount": 3000,
    "splitTradeMinAmount": 3000,
    "minProfitFeeMultiple": 2
  },
  "positions": [
    {
      "code": "022463",
      "name": "富国中证A500ETF联接A",
      "assetType": "open_fund",
      "avgCost": 1.0,
      "shares": 5000,
      "buyDate": "2026-05-01",
      "targetWeight": 0.5,
      "sector": "A股宽基"
    }
  ]
}
```

`tradingCosts` is optional but important for small accounts. Override it with the user's broker fee schedule when known; otherwise use the defaults as conservative estimates for minimum commission and tax drag. For accounts below roughly 20,000 CNY, always evaluate holding amount and order amount together with position percentage: small positions should usually be handled as whole-position decisions instead of repeated partial orders.

Supported `assetType`: `auto`, `stock`, `etf`, `open_fund`, `qdii`. Use `riskRole: sector` when a fund is thematic/aggressive even if the code is not known.

This skill uses a single objective standard. There is no profile/画像 selection, and no `--profile` CLI flag. The default cash reserve floor is 15%. Use optional `cashReserveRatio` (0-1) in `portfolio.json` only when the user explicitly wants a higher cash buffer; it cannot go below 15%.

Validate every position before analysis. Reject invalid codes, negative costs, missing buy dates, and target weights outside 0-1.

## Execution Flow

1. Load `portfolio.json` and validate monthly budget, cash, and positions.
2. Fetch market overview: 上证指数, 深证成指, 创业板指, and 北向资金 when available.
3. For pre-market, next-day plans, technology/growth positions, QDII, or US-related ETFs, fetch overnight global context before A-share action: S&P 500, Nasdaq, Dow, Hang Seng Tech, and NVIDIA via 腾讯API (`web.ifzq.gtimg.cn`) structured data; Philadelphia Semiconductor Index/SOX, US 10Y yield, US Dollar Index, and offshore RMB via WebSearch as supplementary when available.
4. Fetch sector data from 东方财富 for 行业板块 or 概念板块 and rank by daily change, 5-day change, 20-day change, main fund flow, and turnover/volume proxy.
5. Fetch each holding through the degradation chain:
   - Exchange-traded stock/ETF: 东方财富 quote + 东方财富/Tencent K-line.
   - OTC fund/QDII: 东方财富基金历史净值.
6. Calculate MA5/MA10/MA20/MA60, MACD(12/26/9), RSI(6/12/24), deviation, volume ratio, 20-day high/low, and technical trend.
7. For an ETF pool or quantitative request, run `quant` and use the deterministic multi-horizon momentum ranking, volatility-target allocation, market-regime filter, and backtest. Do not substitute the narrative 100-point score for the quant result.
8. For a single-stock discretionary technical report, apply the legacy 100-point scoring model and the objective signal thresholds.
9. Apply chase-high hard and soft rules.
10. Classify the trade setup before giving action: ordinary swing, event-driven high-volatility stock, defensive/value income, broad-index allocation, or sector rotation.
11. Apply portfolio risk role rules: core broad, overseas core, aggressive sector, defensive.
12. Calculate position P&L, portfolio weights, sector concentration, adding ladder, stop-loss, monthly allocation, and redemption-fee warnings.
13. Output the Chinese daily decision board and always include a risk disclaimer.
14. For exchange-traded A-share stocks/ETFs, include trading-session status, T+1 sellability, estimated buy/sell fees, round-trip fee drag, net P&L after fees, and breakeven sell price when cost/shares are available. Do not suggest same-day selling for positions bought today.
15. For small accounts, include trade sizing constraints: holding market value, lot count, whether the position is too small to split, minimum practical order amount, preferred order amount, and the minimum profit needed to cover at least `minProfitFeeMultiple` times round-trip fees. If a position is below `preferredTradeAmount`, avoid recommending partial sells/adds unless risk control requires it.

## Data Source Chain

- A-share quote: 东方财富 `push2.eastmoney.com` -> 新浪 `hq.sinajs.cn`
- A-share K-line: 东方财富 `push2his.eastmoney.com` -> 腾讯 `web.ifzq.gtimg.cn`
- OTC fund NAV: 东方财富基金 `api.fund.eastmoney.com/f10/lsjz`
- Sector data: 东方财富 `api/qt/clist/get`
- North-bound flow: 东方财富 `api/qt/kamt/get`
- Global indices: 腾讯 `web.ifzq.gtimg.cn` for S&P 500 / Nasdaq / Dow / NVIDIA / Hang Seng Tech (structured JSON). WebSearch fallback for SOX, US 10Y yield, Dollar Index, offshore RMB. Use this as sentiment and macro context, not a direct A-share trading signal.
- Optional enhanced data: `TUSHARE_TOKEN` may be read from env, but no paid key is required by default.

SearXNG/WebSearch is only supplementary for news, announcements, macro context, and sources such as SOX or US yields. It must not replace structured quote, K-line, NAV, sector, or fund-flow APIs, and search snippets must never be converted into deterministic market facts.

Each HTTP request uses a 10s timeout and at most 3 attempts. Automatic retry is limited to network interruptions, HTTP 408/425/429, and temporary 5xx responses; 4xx parameter or permission failures are returned immediately. Retries use exponential backoff with jitter and respect numeric `Retry-After` values. Each CLI process shares a keep-alive connection pool capped at 6 outbound requests. Portfolio holdings and quantitative assets use stricter concurrency limits.

The sector list response directly provides daily change, 5-day change, fund-flow, and turnover fields; do not guess any fund-flow field as a 20-day return. Normal sector analysis first ranks the list fields, then verifies at most 10 candidates with bounded K-line requests. Failed or disabled 20-day verification must be exposed through `historyCoverage`, `heatScoreQuality`, and `dataQuality.warnings`; unverified rows use the 5-day trend only as a low-confidence proxy and cannot be promoted to a directional conclusion. If all sources for a required holding or benchmark fail, explain in Chinese which subject failed and how many sources were tried. Optional market, sector, or overseas context may degrade to warnings, but missing required price/K-line facts must still block directional analysis.

## ETF Quantitative Model

Use `node bin/stock-analysis.js quant <codes...>` for ETF selection or rotation. Treat the CLI result as the calculation source of truth.

- Calculate 20/60/120-trading-day returns with weights 40%/35%/25%.
- Standardize each horizon across the supplied ETF universe, then sum the weighted Z-scores.
- Require price above MA60 before an ETF is eligible.
- Select the top three by default. Use two for a small account when minimum commissions would make three positions inefficient.
- Allocate selected ETFs by inverse 20-day annualized volatility, cap each ETF at 35%, and scale total exposure to 12% target annualized volatility. Keep the remainder in cash.
- Use the benchmark's MA200 and rolling 20-day volatility percentile as a regime filter. Default benchmark to `510300`; hold cash when the benchmark is below MA200 or its current volatility exceeds the 80th percentile of its recent sample.
- Rebalance every five common trading days by default.
- Generate each rebalance signal from data available through the previous trading day. Never calculate a signal from the same return period it earns.
- Deduct configured one-way transaction cost from portfolio turnover. Explicitly disclose that minimum commission, market impact, limit-up/limit-down and tracking error are not fully modeled.
- Report CAGR, annualized volatility, Sharpe, maximum drawdown, Calmar, turnover, estimated cost drag, latest completed K-line date, current ranking, target weights, and cash weight.
- Call the output `模型信号` or `目标仓位`, not `强烈买入`. A backtest is historical evidence, not a real-time quote or profit promise.
- Reject comparisons built from fewer than two ETFs or fewer than the required common history rows. Warn that the supplied universe may introduce survivorship bias.

Useful options:

```bash
node bin/stock-analysis.js quant 510300 159915 512100 512660 \
  --benchmark 510300 --history-days 750 --select-count 3 \
  --target-vol 0.12 --max-asset-weight 0.35 \
  --rebalance-every 5 --transaction-cost-rate 0.0003
```

Use `--json` when the user requests auditable rankings, rebalance records, or the full equity curve.

## Legacy 100-Point Scoring

Use this heuristic only for single-stock/holding technical context. Do not describe it as a validated quantitative model and do not let it override an ETF `quant` result.

Use the six dimensions:

| Dimension | Weight | Best Case | Risk Case |
|---|---:|---|---|
| Trend / MA alignment | 30 | MA5>MA10>MA20>MA60 | MA5<MA10<MA20 |
| Deviation from MA5 | 20 | Slightly below or near MA5 | MA5 deviation > +5% |
| MACD | 15 | Golden cross above zero | Death cross |
| Volume | 15 | Shrink pullback | Heavy volume down |
| RSI | 10 | 35-60 healthy | >75 overheated |
| Support | 10 | Near MA20/MA60 support | Far above support |

Signal mapping (single objective standard):

| Strong Buy | Buy | Hold | Wait |
|---:|---:|---:|---:|
| >=72 | >=62 | >=42 | >=28 |

Strong Buy / Buy still require bullish alignment; scores below the wait threshold map to sell/strong-sell by alignment.

## Chase-High Rules

Hard warning: output `追高警告` when any rule is true.

- RSI(6) > 75
- Price deviation from MA5 > +4%
- Price deviation from MA20 > +8%
- Price at 20-day high and volume ratio < 0.8
- Single-day price change > +5% and volume ratio > 2.5
- Price above MA60 by > 30%

Soft warning: output `追高关注` when any rule is true and no hard rule is active.

- RSI(6) between 65 and 75
- Deviation from MA5 between +2% and +4%
- Price within 2% of 20-day high

Never suggest buying or adding when a hard chase-high warning is active.

## Trend And Fund-Flow Quality

When describing "趋势向好", "主力资金流入", "承接强", "洗盘", or "出货", do not treat any single indicator as sufficient. Always classify the quality of the move by combining price trend, volume, fund flow, support/pressure, and intraday behavior. Give one clear label before the detailed explanation.

Use these labels:

| Label | Chinese | Conditions | Action Bias |
|---|---|---|---|
| `healthy_trend_inflow` | 健康趋势流入 | Price above MA5/MA10 or recovering key support; fund flow positive; volume ratio 1.0-2.5; close/last price not far below intraday high; no hard chase warning | Hold or wait for pullback entry |
| `high_chase_inflow` | 高位流入但追高 | Fund flow positive and price rising, but RSI6>75, deviation from MA20>8%, long upper shadow, or volume ratio>2.5 after a large rise | Do not chase; only hold existing small position |
| `accumulation_pullback` | 回踩承接/吸筹 | Price flat or mildly down near MA20/MA10/support; fund flow positive or selling pressure fades; volume not panic-heavy; repeated recovery after dips | Watch for stabilization, allow small planned entry only after recovery confirmation |
| `distribution_risk` | 放量分歧/派发风险 | Price up or flat but main fund flow negative; long upper shadow; large turnover; repeated failure at resistance | Reduce chase confidence; use rebounds to reduce trading position |
| `breakdown_outflow` | 破位流出 | Price breaks key support or MA20/MA10 with heavy volume down and fund flow negative | Do not add; reduce or wait |
| `panic_without_confirmation` | 恐慌杀跌但未确认 | Sharp intraday drop with high volume, but fund flow data is unavailable or mixed and price is still near major support | Do not call it washout yet; wait for reclaim of key level |

For single stocks, if direct main-fund-flow fields are unavailable, clearly say the fund-flow label is inferred from volume, turnover, intraday recovery/failure, and sector fund flow. Do not overstate inferred fund flow as confirmed main inflow/outflow.

For sector and ETF analysis, compare sector daily change vs 5-day and 20-day change, main net inflow vs price change, ETF volume ratio and turnover, key constituent strength or weakness, and whether strength is broad-based or driven by one/two heavyweights.

When trend and fund flow conflict, explicitly say which side has priority. Example: "趋势仍向上，但资金出现高位分歧，操作上按不追高处理" or "资金流入但价格滞涨，先按吸筹观察，不直接买入".

## Overnight Global Context

Use this module when the user asks about early trading, tomorrow's plan, technology/growth sectors, semiconductor/CPO/AI/robotics, QDII, US ETFs, or whether A-shares will follow overseas markets.

Classify overseas context into `顺风`, `中性`, or `逆风`:

| Input | A-share Read-through |
|---|---|
| Nasdaq and SOX rising strongly | Positive for A-share AI, semiconductor, CPO, electronics, ChiNext/KSTAR sentiment |
| NVIDIA/AI leaders rising with sector breadth | Positive for AI compute chain, but still require A-share open confirmation |
| US 10Y yield rising sharply or Dollar Index strong | Pressure on growth/high-valuation assets; reduce chase-high confidence |
| Offshore RMB weakening sharply | Watch foreign-flow and risk appetite pressure |
| China ADR/Hang Seng Tech strong | Positive for China-asset sentiment, technology, consumer internet mappings |
| US market broad selloff | Treat A-share high-position themes cautiously at the open |

Overnight context should adjust the opening bias, not override A-share evidence:

- If overseas context is `顺风` but A-share opens high and fades below VWAP/MA support, do not chase.
- If overseas context is `逆风` but A-share low-opens and shows strong sector breadth plus volume recovery after 15-30 minutes, allow a repair plan.
- For holdings already in profit, overseas `顺风` can justify observing the first 15-30 minutes before selling; it does not justify adding to a hard chase-high signal.
- For event-driven stocks, overseas news is only a catalyst if it maps clearly to the company's business line and the A-share peer group confirms.

## Trade Setup Classification

Always classify the setup before recommending buy, add, hold, reduce, or sell. The same stock can have different actions at different prices and under different catalysts.

| Setup | Typical Examples | Holding Period | Profit Target | Risk Line |
|---|---|---:|---:|---|
| Ordinary swing | TCL, BOE, liquid large-cap cyclicals | 5-15 trading days | 4%-8% | -3% to -5% or support break |
| Event-driven high-volatility | limit-up expectation, AI/CPO/semiconductor catalyst, company interaction/announcement | 3-10 trading days, extend only if catalyst confirms | 8%-15% or board/failed-board rules | -7% to -10% only with small position |
| Defensive/value income | power, utilities, high-dividend SOE | 10-30 trading days or longer | 3%-6% swing or dividend/value rerating | -3% to -5% or thesis deterioration |
| Broad-index allocation | A500, CSI300, ChiNext ETF | 1-3 weeks for swing; quarterly for core | 3%-6% swing | -2% to -4% or MA/support break |
| Sector ETF rotation | semiconductor, chip, AI, robotics ETFs | 5-15 trading days | 5%-10% | -3% to -5% or sector falls out of top rotation |

For ordinary swing trades, do not widen stops merely because the user wants to "wait for breakeven." If the risk line breaks and cannot recover, call it invalid.

For event-driven high-volatility stocks:

- Require an explicit catalyst check before allowing a wider stop: official announcement, exchange filing, investor-relations/interaction response, verified industry news, or clear sector-wide catalyst.
- Use technical levels as confirmation, not the only reason to hold. State the repair levels, such as "stand back above prior support/MA20" or "seal/failed-seal limit-up behavior."
- Position size must be smaller than ordinary swing trades. For small accounts, avoid adding if the stock already exceeds 25%-35% of total assets or if another holding has the same growth/semiconductor/AI exposure.
- If there is no confirmed catalyst, treat it as an ordinary swing and use ordinary swing stops.
- Never justify averaging down only by "it has fallen a lot" or "it may return to cost." Add only on planned pullback support with catalyst intact, volume/price stabilization, and portfolio room.

When a prior stop would have missed a later rebound, explain the trade-off clearly: strict swing stops reduce deep-loss risk but can miss event-driven reversals; holding for event recovery requires smaller sizing and a pre-validated catalyst.

## Pre-Trade Plan And Conditional Orders

Before every new buy or hold/sell decision, write a compact trade plan. Do not let the user switch from short swing to "wait for breakeven" or long-term holding without explicitly changing the setup type and risk budget.

Each plan must include:

- Buy price or current cost
- Setup type: ordinary swing, event-driven, ETF swing, defensive/value, or long-term allocation
- Profit-taking level
- Stop-loss or invalidation level
- Maximum holding period
- Whether adding is allowed
- Add trigger if allowed
- Trigger action: alert only, partial sell, whole-position sell, or no action

Manage every position with three exits, not time alone:

- Price take-profit: sell or reduce near a pressure zone when fee-adjusted profit is meaningful.
- Price stop-loss: sell when support/invalidation breaks after allowing normal volatility for that setup.
- Time stop: exit or downgrade only when the planned holding period is reached and the setup has not worked; do not use time stop to override a valid price stop or a still-valid trend.

Never recommend selling merely because a date arrived. First check whether the original setup is still valid:

- Ordinary swing: if it has not reached target within 5-15 trading days and remains below the expected strength line, exit or switch to watchlist.
- Event-driven stock: if the catalyst fails, failed-board/failed-breakout appears, or the key repair level is lost, exit even before the time limit; if catalyst and price strength remain valid, time can be extended with explicit risk.
- ETF swing: use MA/support and market regime; if price is near support without breakdown, a small time extension is acceptable.
- Defensive/value: time stops are slower; use thesis deterioration, dividend/value change, or support break rather than short-date pressure.
- Long-term allocation: do not use short-term time stops; use allocation drift, valuation, and thesis changes.

When the user asks "how long to hold", answer with both the planned time window and the price/logic exits.

Use conditional orders for sell discipline when the user is likely to hesitate:

- Stop-loss conditions are suitable for conditional orders.
- Profit-taking levels are suitable for alerts or conditional sell orders.
- Small accounts should usually sell the whole position instead of splitting into tiny partial orders.
- If OCO / bracket orders are available, prefer one upper take-profit trigger and one lower stop-loss trigger for event-driven or high-volatility stocks.

Use alerts, not automatic buy orders, for pullback buys:

- Pullback entries require checking whether the decline is shrinking-volume support or heavy-volume breakdown.
- A price-only buy condition can catch a falling knife.
- For buy alerts, require a second confirmation before action: stabilizing near support, recovering above the trigger level, sector breadth improving, or volume pressure easing.

For current small-account examples:

```text
Event-driven stock plan:
买入/成本: 17.025
类型: 事件波段
止盈: 17.60 / 17.80
止损: 16.80
最大持有: 下周二前或事件强度失效
补仓: 不允许
触发动作: 到止盈或止损都整笔处理

ETF swing plan:
买入/成本: 4.097
类型: ETF短波段
止盈: 4.18-4.20
预警: 4.03
止损: 4.00-4.02 且无法快速收回
补仓: 仅在计划区间企稳后允许，默认提醒不自动买入
```

## Portfolio Risk Rules

Use these objective limits before any buy/add recommendation:

| Role | Preferred max / Hard max |
|---|---|
| A股宽基核心仓 | 55% / 65% |
| 标普500 / overseas broad core | 45% / 50% |
| 半导体 / 存储 / 纳斯达克 / sector ETF | 15% / 20% |
| Individual stocks | 12% / 20% |
| Defensive / dividend / low-vol | 45% / 65% |

- `position.maxWeight` can set a stricter or explicit hard max for one position.
- Red dividend / low-vol / bond-like defensive assets can be larger, but still require concentration checks.
- If current weight exceeds preferred max, output `暂停加仓`.
- If current weight exceeds hard max, output `优先降仓`.
- If open fund holding days < 7, warn about possible high short-term redemption fee.

## Overlap And Exposure Rules

Evaluate correlation exposure before new buys. Different tickers can still be the same bet.

- Semiconductor stock + chip ETF + ChiNext ETF often overlap as growth/technology exposure.
- TCL + BOE overlap as display/panel exposure; usually choose one for a small account instead of splitting both.
- CPO/PCB/high-speed connector leaders often overlap with AI compute risk even if they are different industries.
- If two current holdings would likely rise and fall together under the same market narrative, describe the combined exposure and avoid calling the second one a defensive allocation.
- For accounts below roughly 20,000 CNY, prefer one main attack position, one slower swing/core position, and cash. Avoid holding three or more correlated growth positions.

## Profit Taking

For sector/aggressive holdings, profit-taking reminders (objective standard):

- Profit >= 15%: consider selling 1/3.
- Profit >= 25%: consider selling another 1/3.
- Profit >= 35%: take most profit, only keep a small base position.

For A500 / 沪深300 / 标普500 core holdings:

- Do not sell only because of a 5%-10% rise.
- Prefer quarterly or semiannual rebalancing.

## Adding Ladder

Calculate levels from current MA values:

- Pullback to MA10: add 25%
- Pullback to MA20: add 35%
- Pullback to MA60: add 40%

Each level must include trigger price, suggested add amount, stop-loss price, and risk-reward ratio. Never add in a confirmed downtrend: `MA5 < MA10 < MA20`.

## Monthly Allocation

Use `monthlyBudget` from config.

- Reserve the 15% cash buffer floor (or the user's higher `cashReserveRatio`).
- Deploy the remainder only across eligible positions.
- Skip positions with score <42, downtrend, active hard chase-high warning, or risk role add-blocked.
- Never suggest total adds above the monthly budget.
- Keep unused budget as `保留`, not forced buying.

## Output Requirements

Always output Chinese. Include:

- A clear primary judgment before conditional analysis. For trade questions, start with a decisive call such as "buy", "do not buy", "hold", "reduce", "sell", "cancel T plan", or "wait", plus one short reason. Do not only provide conditional branches like "if it holds / if it breaks / if it stands back". Conditional levels are still required, but they must support the primary judgment rather than replace it.
- Trend/fund-flow quality label. For any claim about trend improving, main funds entering/leaving, strong support, washout, or distribution, include one of the labels from `Trend And Fund-Flow Quality` and state whether the evidence is confirmed by fund-flow data or inferred from volume/price behavior.
- Market overview
- Leading and lagging sectors
- Sector rotation signals
- Per-holding P&L, score, RSI, deviation, chase-high status, risk role, adding plan, position weight, and data sources
- Trade setup classification, catalyst status when relevant, invalidation level, planned holding period, and whether the user is mixing short-swing with event-driven logic
- Trading constraints: current session, T+1 sellability, fee-aware net P&L, round-trip fee percentage, breakeven sell price, and minimum-commission warning for small trades
- Trade sizing: holding amount, lot count, whether partial orders are practical, minimum profitable move after fees, and whole-position vs split-order guidance
- Objective analysis standard (single, no profile)
- For ETF pools: model parameters, completed-data date, market regime, momentum ranking, volatility, target weights, cash weight, and out-of-sample limitations
- Monthly budget reserve and deployment table
- Final risk disclaimer: analysis is AI-assisted and not investment advice

Use `references/analysis-prompt-template.md` for narrative analysis framing and `references/output-format-template.md` for the decision board structure when a richer report is requested.
