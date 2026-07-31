# StockWise Skill Agent对接文档

> 接口版本：Wrapper `contractVersion=1.0`  
> Skill版本：`schemaVersion=1.1`  
> 更新时间：2026-07-29

## 1. 接入方式

其他Agent不安装核心分析源码，也不直接执行npm CLI。调用方只通过HTTPS访问云端 `stock-wrapper`：

```text
外部Agent
  → HTTPS请求
  → Nginx
  → stock-wrapper
  → 私有stock-analysis-skill CLI
  → Wrapper契约校验
  → 固定JSON响应
```

推荐服务地址：

```text
https://bdlhxny.com
```

## 2. 当前鉴权能力

当前代码使用单一共享请求头：

```http
X-Internal-Token: <token>
```

服务端环境变量：

```env
INTERNAL_TOKEN=<与调用方相同的token>
```

注意：

- `INTERNAL_TOKEN` 为空时，当前Wrapper会关闭鉴权；生产环境严禁留空。
- 当前版本没有实现 `X-Agent-Id`、逐Agent Token、逐Agent配额和逐Agent吊销。
- 当前接口适用于自有Agent或少量受控合作Agent。
- 面向互不信任的第三方开放前，必须先实现多Agent鉴权、哈希存储、限流、配额和审计。
- 不要在URL、查询字符串、日志或错误消息中传递Token。

## 3. 通用请求约定

所有业务接口使用：

```http
Content-Type: application/json
Accept: application/json
X-Internal-Token: <token>
X-Request-ID: <调用方生成的唯一ID>
```

约束：

- 请求和响应编码均为UTF-8。
- 请求体必须是JSON对象。
- Wrapper请求体上限默认65536字节。
- 单次分析默认超时120秒。
- `X-Request-ID` 用于跨Nginx、Wrapper和Agent日志定位。

## 4. 接口总览

| 能力 | 方法 | 路径 | 用途 |
|---|---|---|---|
| 单标的分析 | POST | `/api/v1/stock/analyze` | A股、ETF、场外基金、QDII |
| 组合分析 | POST | `/api/v1/portfolio/analyze` | 使用真实持仓和资金配置分析 |
| ETF量化轮动 | POST | `/api/v1/quant/analyze` | 多ETF动量、波动率配置和回测 |
| 板块排名 | POST | `/api/v1/sector/analyze` | 行业或概念板块热度排名 |

`GET /health` 和 `GET /ready` 仅用于服务器内部探针，不建议暴露公网。

## 5. 单标的分析

### 5.1 请求

```http
POST /api/v1/stock/analyze
```

```json
{
  "symbol": "600519",
  "assetType": "stock"
}
```

字段：

| 字段 | 必填 | 规则 |
|---|---:|---|
| `symbol` | 是 | 6位数字代码 |
| `assetType` | 否 | `auto`、`stock`、`etf`、`fund`、`open_fund`、`qdii`，默认`auto` |

### 5.2 curl示例

```bash
curl -X POST "https://bdlhxny.com/api/v1/stock/analyze" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Internal-Token: ${STOCKWISE_SKILL_TOKEN}" \
  -H "X-Request-ID: agent-stock-0001" \
  --data '{"symbol":"600519","assetType":"stock"}'
```

## 6. 组合分析

### 6.1 请求

```http
POST /api/v1/portfolio/analyze
```

```json
{
  "monthlyBudget": 5000,
  "cash": 12000,
  "cashReserveRatio": 0.2,
  "positions": [
    {
      "code": "588200",
      "name": "科创芯片ETF",
      "assetType": "etf",
      "avgCost": 1.2,
      "shares": 1000,
      "buyDate": "2026-01-02",
      "targetWeight": 0.3,
      "sector": "半导体",
      "riskRole": "进攻"
    }
  ]
}
```

组合级字段：

| 字段 | 必填 | 规则 |
|---|---:|---|
| `monthlyBudget` | 是 | 大于0 |
| `cash` | 否 | 大于等于0，默认0 |
| `cashReserveRatio` | 否 | 0.15至1，默认0.2 |
| `positions` | 是 | 1至50条真实持仓 |

持仓字段：

| 字段 | 必填 | 规则 |
|---|---:|---|
| `code` | 是 | 6位数字代码 |
| `name` | 是 | 1至100字符 |
| `assetType` | 否 | 与单标的接口一致 |
| `avgCost` | 是 | 大于0 |
| `shares` | 是 | 大于0 |
| `buyDate` | 是 | `YYYY-MM-DD` |
| `targetWeight` | 是 | 0至1 |
| `sector` | 否 | 最多50字符 |
| `riskRole` | 否 | 最多30字符 |

组合接口禁止使用示例持仓代替真实用户数据。Wrapper只在单次执行期间创建权限为0600的临时文件，并在成功或失败后删除。

## 7. ETF量化轮动

### 7.1 请求

```http
POST /api/v1/quant/analyze
```

```json
{
  "codes": ["510300", "159915", "512100"],
  "benchmark": "510300"
}
```

字段：

| 字段 | 必填 | 规则 |
|---|---:|---|
| `codes` | 是 | 至少两个不重复的6位代码 |
| `benchmark` | 否 | 6位代码 |

## 8. 板块排名

### 8.1 请求

```http
POST /api/v1/sector/analyze
```

```json
{
  "type": "industry",
  "limit": 20
}
```

字段：

| 字段 | 必填 | 规则 |
|---|---:|---|
| `type` | 否 | `industry`或`concept`，默认`industry` |
| `limit` | 否 | 1至100，默认20 |

## 9. 成功响应

HTTP响应外层是Wrapper信封，`data`字段是原生Skill结果：

```json
{
  "success": true,
  "requestId": "agent-stock-0001",
  "contractVersion": "1.0",
  "command": "stock",
  "asOf": "2026-07-29 15:30:00",
  "data": {
    "schemaVersion": "1.1",
    "command": "stock",
    "timezone": "Asia/Shanghai",
    "asOf": "2026-07-29 15:30:00",
    "dataQuality": {
      "status": "realtime",
      "allowsDirectionalSignal": true
    },
    "methodology": {
      "id": "stockwise-objective-analysis",
      "version": "1.0.0",
      "nature": "deterministic_engine_with_declared_heuristics",
      "rules": []
    },
    "decisionBasis": {
      "verdict": "hold",
      "gates": [],
      "evidence": [],
      "limitations": []
    },
    "data": {},
    "sources": {}
  },
  "error": null
}
```

调用方必须依次校验：

1. HTTP状态码为2xx。
2. `success=true`。
3. `contractVersion=1.0`。
4. `data.schemaVersion=1.1`。
5. `data.methodology.id=stockwise-objective-analysis`。
6. `methodology.version`、`decisionBasis`、`dataQuality`和`asOf`存在。

## 10. Agent消费规则

Agent必须遵守：

- `dataQuality.allowsDirectionalSignal=false` 时，不得生成买入、卖出、加仓或减仓方向结论。
- `decisionBasis.gates` 中任一硬门禁失败时，必须保留对应 `consequence`。
- `CHASE-HARD-001` 触发时，禁止买入和加仓。
- `heuristic` 只能描述为规则化评分或排序，不得转换成胜率或预期收益。
- 必须向最终用户披露 `decisionBasis.limitations` 中与结论相关的限制。
- 大模型不能重新计算或覆盖Skill返回的硬门禁。
- 不得把搜索结果、用户观点或模型常识伪装成Skill的确定性观测。

推荐保存：

- `requestId`
- `command`
- `asOf`
- `methodology.version`
- Rule ID
- `decisionBasis`
- 调用耗时
- HTTP状态和错误码

不得保存Token，也不得保存模型隐藏思维链。

## 11. 错误响应

```json
{
  "success": false,
  "requestId": "agent-stock-0001",
  "contractVersion": "1.0",
  "data": null,
  "error": {
    "code": "INVALID_SYMBOL",
    "message": "symbol 必须是 6 位数字代码",
    "details": null
  }
}
```

常见错误：

| HTTP状态 | 错误码示例 | 是否建议重试 |
|---:|---|---|
| 400 | `INVALID_JSON`、`INVALID_SYMBOL`、`INVALID_PORTFOLIO` | 否，修正请求 |
| 401 | `UNAUTHORIZED` | 否，检查Token |
| 404 | `NOT_FOUND` | 否，检查路径 |
| 413 | `BODY_TOO_LARGE` | 否，缩小请求 |
| 429 | `WRAPPER_BUSY` | 可在退避后重试一次 |
| 502 | `SKILL_INVALID_JSON`、`SKILL_EXECUTION_FAILED`、数据源错误 | 默认不重试，记录requestId |
| 503 | `SKILL_NOT_READY` | 可在服务恢复后重试 |
| 504 | `SKILL_TIMEOUT` | 不自动连续重试 |

当前接口没有幂等缓存。调用方不得进行无上限重试；需要重试时最多一次，并保留相同 `X-Request-ID` 方便排查。

## 12. Java Agent配置

StockWise Java后端使用：

```env
STOCK_WRAPPER_URL=https://bdlhxny.com
STOCK_WRAPPER_TOKEN=<云端INTERNAL_TOKEN>
STOCK_WRAPPER_CONNECT_TIMEOUT_MS=5000
STOCK_WRAPPER_REQUEST_TIMEOUT_MS=120000
```

同一Docker网络内部调用时使用：

```env
STOCK_WRAPPER_URL=http://stock-wrapper:3001
```

## 13. 其他Agent Tool定义示例

```json
{
  "name": "stockwise_stock_analysis",
  "description": "获取经过数据时效、风险门禁和方法论追溯的单标的分析",
  "method": "POST",
  "url": "https://bdlhxny.com/api/v1/stock/analyze",
  "headers": {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Internal-Token": "${STOCKWISE_SKILL_TOKEN}",
    "X-Request-ID": "${REQUEST_ID}"
  },
  "inputSchema": {
    "type": "object",
    "required": ["symbol"],
    "properties": {
      "symbol": {
        "type": "string",
        "pattern": "^[0-9]{6}$"
      },
      "assetType": {
        "type": "string",
        "enum": ["auto", "stock", "etf", "fund", "open_fund", "qdii"],
        "default": "auto"
      }
    }
  }
}
```

## 14. 正式对外开放前检查

当前单Token版本可以供自有Agent和受控测试Agent使用。面向多个客户正式开放前，必须完成：

- `X-Agent-Id + X-Agent-Token`。
- Token哈希存储、有效期和吊销。
- 单Agent限流、并发和每日配额。
- 调用审计和异常告警。
- OpenAPI 3.1文档。
- 契约兼容策略和版本废弃通知。
- 费用、服务等级和隐私条款。

