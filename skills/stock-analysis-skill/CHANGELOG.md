# Changelog

## 0.4.0

- 所有“今天/盘中/保存时间”统一使用 `Asia/Shanghai`。
- 新增 2026 年上交所休市日历校验，非覆盖年份明确警告。
- 解析新浪行情日期时间，并读取东方财富时间戳字段。
- 新增 `dataQuality`：行情时间、K线/净值日期、延迟、临时值、可信状态。
- 盘中行情过期、时间未知或K线不同步时，方向信号强制降为观望并阻断加仓。
- 实时行情可临时补齐当天K线，技术指标明确标记为盘中临时值。
- 场外基金/QDII明确标记为非实时净值及滞后交易日数。
- 移除分析提示模板中已废弃的保守/平衡/激进画像逻辑。
- 升级 `axios` 至 1.18.1、`form-data` 至 4.0.6，并移除未使用的 `cheerio`/`undici` 依赖链；`npm audit` 清零。

## 0.3.0

- Added selectable `conservative`, `balanced`, and `aggressive` analysis profiles.
- Added `--profile` CLI option and `analysisProfile` portfolio config field.
- Adjusted reserve floors, score signals, allocation thresholds, profit-taking reminders, and risk-role limits by profile.
- Kept chase-high hard blocks and confirmed-downtrend add blocks active for every profile.

## 0.2.0

- Added OTC fund / ETF-linked fund support through Eastmoney fund NAV history.
- Added `--asset` option for `stock` command: `stock`, `etf`, `open_fund`, `qdii`, `auto`.
- Added risk-role classification for A500, S&P500, semiconductor/storage, Nasdaq-like growth, defensive assets, and single stocks.
- Added position-level risk warnings: sector ETF overweight, hard max breach, chase-high block, and less-than-7-day open-fund redemption-fee warning.
- Updated portfolio examples to match a simple `A500 + S&P500 + semiconductor` structure.
- Updated SKILL.md and README rules for core holdings vs aggressive holdings.
