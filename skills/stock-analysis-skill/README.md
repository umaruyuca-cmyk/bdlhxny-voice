# A-Share / ETF / Fund Analysis Skill

A股、场内 ETF、场外 ETF 联接 / QDII 基金分析 Skill，内置 npm CLI。它会抓取免费行情/净值数据，计算技术指标、100 分制评分、追高风险、仓位风控、补仓梯度和月度资金分配，并提供 ETF 多周期动量、波动率目标仓位及历史回测。

完整的证据等级、公式、阈值、Rule ID、研究来源和当前限制见 [`references/methodology.md`](references/methodology.md)。机器 JSON 使用 Schema `1.1`，每次结果都包含 `methodology` 和 `decisionBasis`，用于说明结论依据而不是只给最终标签。

**本 Skill 只使用一套客观分析标准**：不区分保守/一般/激进画像，所有判断基于技术指标本身的事实，使用同一套信号阈值与仓位规则。追高硬警告和确认下跌趋势仍强制阻断加仓。

```text
A500 / 沪深300 / 中证500 = A股宽基核心仓
标普500 = 海外宽基核心仓
半导体 / 存储 / 纳斯达克 = 进攻仓，适用统一的仓位上限
```

## 量化框架来源与边界

本项目的 ETF 量化模块是一个**参考公开基础研究、自行组合参数的实验性研究框架**，不是任何一篇论文的原版复现，也不是从机构或商业平台复制的成熟策略。

框架主要借鉴以下公开研究思想：

- 动量与趋势延续：参考 Moskowitz、Ooi、Pedersen 的 [Time Series Momentum](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463)。论文研究的是多个期货资产上的时间序列动量；本项目是在给定 ETF 池中进行横截面排名，因此只属于思想借鉴，不是论文策略复现。
- 波动率管理：参考 Moreira、Muir 的 [Volatility Managed Portfolios](https://www.nber.org/papers/w22208)，借鉴“波动率升高时降低风险敞口”的原则。本项目使用逆波动率和目标波动率进行简化实现，与论文公式并不完全相同。
- 风险分配：逆波动率仓位来自风险平价类常见思想。目前版本没有实现完整协方差风险模型，也没有实现 HRP。HRP 的相关研究可参见 López de Prado 的 [Building Diversified Portfolios that Outperform Out-of-Sample](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678)。
- 回测纪律：信号只使用当时已经可获得的数据，前一交易日生成信号，之后的交易日才计算策略收益，避免明显的未来函数。

以下参数是本项目为了建立 V1 基准而自行设定的工程参数，并非论文给出的标准答案：

| 参数 | 当前默认值 |
|---|---:|
| 动量周期 | 20 / 60 / 120 个交易日 |
| 动量权重 | 40% / 35% / 25% |
| ETF准入过滤 | 收盘价高于 MA60 |
| 市场状态过滤 | 基准高于 MA200，且20日波动率不高于近期80%分位 |
| 默认基准 | 沪深300ETF `510300` |
| 默认选择数量 | 排名前3只ETF |
| 单只最高权重 | 35% |
| 组合目标年化波动率 | 12% |
| 调仓频率 | 每5个共同交易日 |

因此，本项目只能表述为：

> 参考公开动量、趋势跟随和波动率管理研究构建的实验性 ETF 量化框架。具体参数及组合方式由本项目自行设定，尚未经过充分的 A 股长期样本外验证。

不得将其描述为“论文已经证明在A股有效”“论文原版策略”“稳定盈利模型”或“实盘收益保证”。回测结果可能受到参数选择、ETF存续历史、幸存者偏差、数据质量、交易成本和市场制度变化影响。模型跑通不等于模型有效；应同时比较买入持有基准，并继续进行滚动样本外测试。

## Install

```bash
npm install
```

Node.js 18+ required. No Python or pip dependencies.

## Usage

```bash
node bin/stock-analysis.js --help
node bin/stock-analysis.js sector
node bin/stock-analysis.js sector --type concept --limit 15
node bin/stock-analysis.js stock 159801 --asset etf
node bin/stock-analysis.js stock 022463 --asset open_fund
node bin/stock-analysis.js stock 017641 --asset qdii
node bin/stock-analysis.js portfolio --config templates/portfolio.example.json
node bin/stock-analysis.js quant 510300 159915 512100 512660 --benchmark 510300 --history-days 750
```

量化命令可使用 `--json` 输出可审计的动量排名、目标仓位、调仓记录和净值曲线：

```bash
node bin/stock-analysis.js quant 510300 159915 512100 \
  --benchmark 510300 \
  --target-vol 0.12 \
  --max-asset-weight 0.35 \
  --rebalance-every 5 \
  --transaction-cost-rate 0.0003 \
  --json
```

人工文本模式缺少 `portfolio.json` 时会回退到示例配置并告警；`portfolio --json` 机器模式会直接返回 `PORTFOLIO_CONFIG_NOT_FOUND`，绝不使用示例持仓。

> 历史版本支持 `--profile conservative|balanced|aggressive` 选择风险画像，现已移除：统一为客观标准。`portfolio.json` 中残留的 `analysisProfile` 字段会被忽略并给出提示，可删除。

## portfolio.json

```json
{
  "monthlyBudget": 5000,
  "cash": 0,
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
    },
    {
      "code": "017641",
      "name": "摩根标普500指数QDII人民币A",
      "assetType": "qdii",
      "avgCost": 1.0,
      "shares": 4000,
      "buyDate": "2026-05-01",
      "targetWeight": 0.4,
      "sector": "海外宽基"
    },
    {
      "code": "159801",
      "name": "广发国证半导体芯片ETF",
      "assetType": "etf",
      "riskRole": "sector",
      "avgCost": 1.2,
      "shares": 830,
      "buyDate": "2026-05-20",
      "targetWeight": 0.1,
      "sector": "半导体"
    }
  ]
}
```

### assetType / riskRole

- `stock`: A股个股
- `etf`: 场内 ETF，例如 159801、510300
- `open_fund`: 场外基金 / ETF 联接，例如 022463、008888
- `qdii`: QDII / 海外指数基金，例如 017641
- `riskRole: sector`: 强制按行业进攻仓风控
- `riskRole: broad/core`: 强制按宽基核心仓风控

### cashReserveRatio（可选）

默认现金缓冲下限为 15%。若需自定义，可在 `portfolio.json` 设置 `cashReserveRatio`（0-1），会覆盖默认值；无法低于默认 15%。

## Data Sources

- Quotes and indexes: 东方财富, 新浪
- K-line history: 东方财富, 腾讯
- OTC fund NAV: 东方财富基金历史净值
- Sectors: 东方财富行业/概念板块
- North-bound flow: 东方财富
- Optional env: `TUSHARE_TOKEN`

The HTTP client uses 10s timeout, 3 retries, and fallback source chains.

## Shared Rules

- Hard chase-high warnings always block new buys.
- Never add in confirmed downtrend: `MA5 < MA10 < MA20`.
- Keep at least the 15% monthly cash reserve floor.
- Every action includes a stop-loss reference.
- Open fund held less than 7 days should trigger redemption-fee warning.
- Exchange-traded A-share stocks/ETFs include trading-session checks, T+1 sellability, one-lot fee estimates, round-trip fee drag, net P&L after estimated fees, and breakeven sell price.
- Small positions should be evaluated after minimum commission. When minimum commission dominates, prefer fewer combined orders instead of repeated one-lot partial trades.
- Small-account decisions must evaluate holding amount and order amount, not only position percentage. Positions below the preferred trade amount should usually be handled as whole-position decisions instead of split orders.

## Trading costs and T+1

Add optional `tradingCosts` to `portfolio.json` when your broker fee differs:

```json
{
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
  }
}
```

For ad-hoc stock analysis, pass holding fields to include T+1 and fee-aware output:

```bash
node bin/stock-analysis.js stock 600703 --asset stock --shares 200 --avg-cost 16.975 --buy-date 2026-05-29
```

If `buyDate` is today for an exchange-traded stock/ETF, the CLI warns that the position cannot be sold until the next trading day. OTC funds/QDII are treated as NAV subscription/redemption products instead of intraday exchange trades.

## Objective Standard Defaults

统一客观标准的信号阈值与仓位上限：

| 项目 | 阈值 |
|---|---|
| Strong Buy | >=72（且多头排列） |
| Buy | >=62（且偏多排列） |
| Hold | >=42 |
| Wait | >=28 |
| 现金缓冲下限 | 15% |

| 风险角色 | 建议上限 / 硬上限 |
|---|---|
| A股宽基核心仓 | 55% / 65% |
| 海外宽基核心仓 | 45% / 50% |
| 行业/海外科技进攻仓 | 15% / 20% |
| 个股 | 12% / 20% |
| 防守/低波仓 | 45% / 65% |

## Profit-taking defaults

For sector / aggressive holdings:

- Profit >= 15%: consider selling 1/3.
- Profit >= 25%: consider selling another 1/3.
- Profit >= 35%: take most profit, only keep a small base position.

For broad core holdings:

- Do not sell only because of a 5%-10% rise.
- Prefer quarterly / semiannual rebalancing.

Risk notice: output is AI-assisted analysis, not investment advice.
