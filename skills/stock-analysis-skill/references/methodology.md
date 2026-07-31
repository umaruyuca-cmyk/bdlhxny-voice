# StockWise 分析方法论与适用边界

## 目录

1. 方法定位
2. 证据等级
3. 数据来源与时效
4. 单标的技术分析
5. 追高与交易风控
6. 组合分析与资金分配
7. ETF 量化轮动与回测
8. 板块轮动
9. 基本面范围
10. 规则追溯表
11. 当前限制与升级标准

## 1. 方法定位

本 Skill 是确定性分析与风控引擎，不是收益预测模型，也不是持牌投资顾问。相同输入、相同数据时间和相同规则版本必须得到相同结果。大模型只能解释 Skill 已输出的事实，不能修改指标、阈值、时效门禁或风险拦截结果。

方法论标识固定为 `stockwise-objective-analysis`。修改公式、阈值或门禁含义时必须升级 `methodology.version`，补回归测试，并在 JSON 的 `methodology` 与 `decisionBasis` 中留下可回放依据。

## 2. 证据等级

| 等级 | 含义 | 当前内容 |
|---|---|---|
| `deterministic` | 公式可复算，不依赖模型判断 | MA、MACD、RSI、收益率、波动率、盈亏、权重、费用 |
| `research_based` | 方法方向有公开研究支持，但参数是本项目实现 | 动量排序、波动率目标、趋势过滤 |
| `risk_policy` | 为降低错误交易风险设置的硬门禁 | 数据过期阻断、追高禁止、现金底线、仓位上限 |
| `heuristic` | 工程启发式，尚未完成独立样本外校准 | 单股 100 分制、板块热度权重、补仓梯度、信号分界 |

不得把 `heuristic` 描述成统计显著的收益预测，也不得把历史回测描述成未来收益保证。

## 3. 数据来源与时效

- A 股/ETF 行情：东方财富，失败时降级新浪。
- A 股/ETF K 线：东方财富，失败时降级腾讯。
- 场外基金/QDII 净值：东方财富基金历史净值。
- 板块：东方财富行业/概念结构化行情；列表响应中的当日、5 日、资金流和换手字段用于初筛，再对最多 10 个候选板块受控补拉 K 线核验 20 日表现。不得把资金流字段猜测成 20 日涨跌。
- 海外指数：腾讯结构化行情。
- 新闻、公告与宏观补充：可使用 SearXNG/WebSearch，但搜索摘要不得替代结构化行情、K 线、净值或资金流事实。
- 所有交易日、时间戳和“今天”均按 `Asia/Shanghai`。

盘中行情年龄不超过 120 秒且存在北京时间当日 K 线时才允许方向性信号；超过 120 秒、缺少时间戳、最新 K 线不同步或数据源失败时强制 `allowsDirectionalSignal=false`。场外基金只按最新公布净值分析，不得称为实时价格。

数据访问层对单个请求设置 10 秒超时和最多 3 次尝试，只重试网络中断、限流与临时服务端错误，并使用带随机抖动的指数退避。每个 CLI 进程限制共享 HTTP 连接数；组合持仓和量化标的进一步限制并发。市场、板块和海外背景可以带 warning 安全降级，但任何必需持仓或基准缺少价格/K线时不得生成方向性结论。

## 4. 单标的技术分析

确定性指标：

- MA5/10/20/60：对应窗口收盘价算术平均。
- MACD：EMA(12)-EMA(26)，Signal 为 9 期 EMA。
- RSI6/12/24：按涨跌幅平滑结果计算。
- 乖离率：`(price - MA) / MA × 100%`。
- 量比：当前量与比较窗口平均量之比；盘中量必须按已交易时间缩放。
- 支撑/压力：最近 20 日高低点与关键均线。

单股 100 分制由趋势 30、MA5 乖离 20、MACD 15、量价 15、RSI 10、支撑 10 构成。信号阈值为 72/62/42/28，并受均线排列、基本面否决、数据时效和追高硬门禁覆盖。该分值是规则化排序工具，不是已校准胜率或预期收益。

## 5. 追高与交易风控

任一硬条件触发即禁止新增买入：

- RSI6 > 75。
- MA5 乖离 > 4%。
- MA20 乖离 > 8%。
- 接近 20 日新高且量比 < 0.8。
- 单日涨幅 > 5% 且量比 > 2.5。
- MA60 乖离 > 30%。

软条件包括 RSI6 处于 65–75、MA5 乖离处于 2%–4%、距离 20 日高点小于 2%。软条件只降低追价意愿，不单独产生卖出结论。

交易费用使用用户配置或默认佣金、最低佣金、印花税和过户费；A 股卖出遵守 T+1。止损和补仓属于风险计划，不是成交指令。

## 6. 组合分析与资金分配

- 当前权重：`持仓市值 / (持仓市值 + 现金)`。
- 单板块权重达到 35% 时给出集中风险。
- 现金保留比例不得低于 15%。
- MA5 < MA10 < MA20、追高硬警告、数据质量不足或超过仓位上限时禁止加仓。
- 候选分配权重由目标权重、技术分数、欠配程度和回踩条件共同决定。
- 建议金额低于最低有效交易金额时保留现金，避免最低佣金侵蚀。

当前组合模块尚未使用完整收益协方差矩阵、相关性聚类、VaR/CVaR 或压力测试，因此不能称为机构级组合优化。

## 7. ETF 量化轮动与回测

模型使用 20/60/120 日动量，权重为 40%/35%/25%，对同一候选池横截面 Z 标准化后加权排名；价格必须高于 MA60。入选标的按 20 日年化波动率倒数分配，单品种上限 35%，组合目标年化波动率 12%。

基准跌破 MA200 或 20 日波动率超过近 252 日样本的 80 分位时转为现金。默认每 5 个共同交易日调仓，单边成本率 0.03%。信号仅使用前一交易日及更早数据，避免未来函数。

量化资产池仍应使用可交易 ETF。基准可以使用 ETF，也可以使用代码表中明确支持的上证、沪深300、中证500、中证1000、科创50、深证成指和创业板等指数；指数必须使用独立市场映射，不得套用普通股票代码前缀猜测。

动量和波动率管理的方向与公开资产定价研究一致，但本实现的具体窗口、ETF 池、A 股交易约束和参数没有因此自动获得统计有效性：

- Moskowitz、Ooi、Pedersen，《Time Series Momentum》：https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum
- Moreira、Muir，《Volatility Managed Portfolios》：https://www.nber.org/papers/w22208
- Moskowitz、Grinblatt，《Do Industries Explain Momentum?》：https://www.aqr.com/Insights/Research/Journal-Article/Do-Industries-Explain-Momentum

每次实盘使用前仍应执行滚动样本外验证、参数敏感性、幸存者偏差检查和真实交易成本压力测试。

## 8. 板块轮动

板块热度 `sector-heat-v2` 先在同一板块类型、同一数据快照内，把各组成项转换为 0–100 的横截面分位分数，再按固定权重计算：

```text
0.35 × 当日涨跌分位
+ 0.25 × 5日涨跌分位
+ 0.15 × 20日涨跌分位
+ 0.15 × 主力净流入分位
+ 0.10 × 换手率分位
```

缺失分项不得补零，也不得用 5 日涨跌冒充 20 日涨跌；计算时只对真实可用分项按可用权重重标，并通过 `missingComponents`、`availableWeight` 和 `heatScoreQuality` 降低结论置信度。分数用于排序和发现持续强弱、价格资金背离，不是收益概率。JSON 必须返回 `heatScore`、`heatScoreBreakdown`、`formulaVersion`、标准化样本量和组成字段，调用方不得只展示排名而隐藏依据。

互联网新闻、搜索结果和讨论关键词不进入 `sector-heat-v2`。它们只能由编排层形成独立的 `attentionHeat` 搜索证据代理，并明确说明搜索结果不等于真实搜索量、平台互动量或特定人群数量。

## 9. 基本面范围

当前基本面只覆盖数据源可获得的 PE、PB、市值和少量红旗/否决规则，没有完整财报质量、现金流、盈利预测、行业估值分位、公司治理和公告事件核验。因此：

- 可以作为技术信号的风险修正。
- 不能独立形成长期价值判断。
- 不能把缺失基本面数据解释为“基本面良好”。

## 10. 规则追溯表

| Rule ID | 类型 | 代码真源 | 输出位置 |
|---|---|---|---|
| `DATA-FRESH-001` | risk_policy | `src/analysis/freshness.js` | `dataQuality`、`decisionBasis.gates` |
| `TECH-IND-001` | deterministic | `src/analysis/technical.js` | `data.technical` |
| `SCORE-HEURISTIC-001` | heuristic | `src/analysis/scoring.js`、`profiles.js` | `data.score`、`decisionBasis.evidence` |
| `CHASE-HARD-001` | risk_policy | `src/analysis/chase-high.js` | `data.chase`、`decisionBasis.gates` |
| `PORT-RISK-001` | risk_policy | `src/analysis/asset-rules.js`、`position.js` | `data.holdings[].risk` |
| `ALLOC-HEURISTIC-001` | heuristic | `src/analysis/allocation.js` | `data.allocation` |
| `QUANT-MOM-001` | research_based | `src/analysis/quant.js` | `data.currentRanking` |
| `QUANT-VOL-001` | research_based | `src/analysis/quant.js` | `data.currentAllocation` |
| `BACKTEST-NOFUTURE-001` | deterministic | `src/analysis/quant.js` | `data.rebalances`、`data.metrics` |
| `SECTOR-HEAT-001` | heuristic | `src/data/sector.js` | `data.sectors[].heatScore` |

## 11. 当前限制与升级标准

当前不足：

- 单股启发式阈值缺少 A 股分市场、行业和波动状态的样本外校准。
- 板块资金字段依赖供应商口径，不等同于可审计交易所逐笔资金。
- 回测未完整模拟涨跌停、停牌、申赎、冲击成本、跟踪误差和最低佣金。
- 基本面和事件研究深度不足。
- 组合风险尚未包含相关性和压力测试。

升级为更专业版本至少需要：

1. 固定可复现数据快照与基准。
2. 建立训练期、验证期、样本外测试期。
3. 输出胜率、盈亏比、覆盖率、换手、成本后收益、回撤和参数敏感性。
4. 按资产类别与市场状态分层评估。
5. 对每次规则变更升级方法论版本并保留对照结果。
