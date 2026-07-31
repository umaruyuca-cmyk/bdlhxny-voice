# JSON 契约

后台系统必须给真实 Command 添加 `--json`，并且只解析 stdout。stderr 仅用于诊断。

四个 Command 共用以下顶层字段：

```json
{
  "schemaVersion": "1.1",
  "command": "stock|portfolio|quant|sector",
  "timezone": "Asia/Shanghai",
  "asOf": "已核验的市场数据时间",
  "request": {},
  "dataQuality": {
    "status": "verified|limited|unknown",
    "asOf": "已核验的市场数据时间",
    "allowsDirectionalSignal": false,
    "provisional": false,
    "warnings": []
  },
  "data": {},
  "sources": {},
  "methodology": {
    "id": "stockwise-objective-analysis",
    "version": "1.0.0",
    "rules": []
  },
  "decisionBasis": {
    "verdict": "规则结论",
    "gates": [],
    "evidence": [],
    "limitations": []
  }
}
```

规则：

- stdout 只能包含一个 UTF-8 JSON 文档。
- `asOf` 必须来自行情、K线、净值或板块数据。
- 调用方必须同时校验 `schemaVersion`、`command`、`asOf` 和 `dataQuality`。
- 调用方必须保留 `methodology.version` 和 `decisionBasis`，用于回放当次分析的公式、门禁、观测值与限制。
- `sector` 的每个排名项必须保留 `heatScoreBreakdown`，其中包含原始值、横截面分位、声明权重、有效权重、贡献值和样本量；缺失项不得由调用方补零或猜测。
- 外围讨论度不属于 `sector` Command 的确定性行情热度，必须由调用方使用独立证据结构承载。
- 禁止把文本看板包装成成功 JSON。
- 失败使用非零退出码，stderr 返回：

```json
{
  "schemaVersion": "1.1",
  "command": "portfolio",
  "timezone": "Asia/Shanghai",
  "asOf": null,
  "error": {
    "code": "PORTFOLIO_CONFIG_NOT_FOUND",
    "message": "真实持仓配置文件不存在"
  }
}
```
