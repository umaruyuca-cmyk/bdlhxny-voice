# StockWise 标的搜索联想功能 — 开发 Prompt

> **版本**: v1.0 | **日期**: 2026-07-30
> **依赖**: PRD v3.3、`08-dev-prompt.md`，冲突时以 PRD v3.3 为准。
> **用途**: 驱动编码 AI 按步骤实现前端标的搜索联想 + 后端 lookup API + stock-wrapper 整合。

---

## 背景与问题

当前原型 `stockwise-chat-v2.html` 的标的选择弹窗是纯前端 mock（写死 3 只股票）。实际上 A 股 5000+、ETF 800+、场外基金上万只，无法用静态列表覆盖。

用户在前端弹窗搜索框输入名称/代码/拼音时，需要实时联想出结构化候选列表（类似百度搜索下拉），选中后将标的持久化为当前会话的 `currentInstrument`，后续每条对话消息自动携带。

---

## 核心设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 标的搜索数据源 | 东方财富 suggest API | 免费、全市场覆盖（股票+ETF+LOF+场外基金+可转债）、返回结构化 JSON |
| 前端直连还是后端代理 | stock-wrapper 代理 | 统一下游管理，可切换数据源（东财挂了换新浪），前端不感知数据源 |
| WebSearch (SearXNG) 是否参与 | 否 | SearXNG 搜的是网页，用于 agent 后台分析证据收集；标的搜索是结构化金融数据 |
| 与现有 stock-wrapper 的关系 | 共用 stock-wrapper，新增 `lookup` 端点 | 复用已有部署、鉴权和健康检查，不增加新服务 |

---

## 一、数据源：东方财富 suggest API

### 1.1 接口信息

```
GET https://searchadapter.eastmoney.com/api/suggest/get
  ?input=茅台
  &token=...（东财固定 token，可从其主页抓取）
  &count=10
```

### 1.2 返回结构（简化）

```json
{
  "QuotationCodeTable": {
    "Data": [
      {
        "Code": "600519",
        "Name": "贵州茅台",
        "Market": "SH",
        "SecurityType": "stock",
        "SecurityTypeName": "A股",
        "MktNum": "1"
      },
      {
        "Code": "161725",
        "Name": "白酒基金LOF",
        "Market": "SZ",
        "SecurityType": "fund",
        "SecurityTypeName": "LOF",
        "MktNum": "0"
      }
    ]
  }
}
```

### 1.3 字段映射

| 东财字段 | 标准化字段 | 说明 |
|----------|-----------|------|
| `Code` | `code` | 6 位代码 |
| `Name` | `name` | 标的名称 |
| `SecurityType` | `assetType` | `stock` / `etf` / `fund` / `bond` |
| `Market` | `market` | `SH` / `SZ` / `BJ` |
| `SecurityTypeName` | `typeName` | 中文类别：A股 / 场内ETF / LOF / 场外基金 |

### 1.4 stock-wrapper 输出标准化

stock-wrapper 的 `lookup` 端点返回固定结构：

```json
{
  "schemaVersion": "1.0",
  "keyword": "茅台",
  "asOf": "2026-07-30T14:30:00+08:00",
  "items": [
    {
      "code": "600519",
      "name": "贵州茅台",
      "assetType": "stock",
      "market": "SH",
      "typeName": "A股",
      "shortCode": "SH"
    },
    {
      "code": "161725",
      "name": "白酒基金LOF",
      "assetType": "fund",
      "market": "SZ",
      "typeName": "LOF",
      "shortCode": "SZ"
    }
  ]
}
```

`shortCode` 逻辑：
- 场内 ETF + 沪深市场 → `ETF`
- 股票深市 → `SZ`，沪市 → `SH`，北交 → `BJ`
- 场外基金 → `FD`
- LOF → `LOF`

---

## 二、后端实现

### 2.1 stock-wrapper 新增 lookup 端点

**文件**: `stock-wrapper/src/lookup.js`（新建）

```
POST /lookup
Content-Type: application/json
Authorization: Bearer <INTERNAL_TOKEN>

请求:
{
  "keyword": "茅台",
  "limit": 8
}

响应:
{
  "schemaVersion": "1.0",
  "keyword": "茅台",
  "asOf": "...",
  "items": [...]
}
```

实现要点：
- 调用东方财富 suggest API（`GET`，query string 拼接）
- 解析东财 JSON → 映射为标准化 `items`
- 保留 `SecurityType` 判断逻辑（区分 stock/etf/fund）
- 失败时返回结构化错误，非零退出码
- 超时 5 秒

### 2.2 stockwise-backend 新增 API

**新建 Controller 方法** (`StockController` 或新建 `LookupController`):

```java
/**
 * 标的搜索联想。
 * 仅调用股票信息 API，不消耗 Token，不进入 Agent Run 审计。
 */
@GetMapping("/api/v1/stocks/lookup")
public ResponseEntity<?> lookup(
        @RequestParam String keyword,
        @RequestParam(defaultValue = "8") int limit) {
    // 1. 参数校验：keyword 非空，limit 1-20
    // 2. 调用 StockLookupGateway → stock-wrapper /lookup
    // 3. 返回标准化 items 列表
}
```

**新建 Gateway** (`StockLookupGateway`):

```java
public interface StockLookupGateway {
    List<StockLookupItem> lookup(String keyword, int limit);
}
```

实现类 `HttpStockLookupGateway`:
- 复用 stock-wrapper 的 HTTP 客户端配置（baseUrl、token、超时）
- POST `/lookup`，携带 `INTERNAL_TOKEN`
- 解析 wrapper JSON → `List<StockLookupItem>`
- 失败降级返回空列表，不抛异常阻塞主流程

**新建 DTO**:

```java
public record StockLookupItem(
    String code,
    String name,
    String assetType,   // stock / etf / fund
    String market,      // SH / SZ / BJ
    String typeName,    // A股 / 场内ETF / LOF
    String shortCode    // SH / SZ / ETF / FD / LOF
) {}
```

### 2.3 关键约束

- **不进入 Agent Run 审计** — 这是结构性查询，不是分析推理
- **不消耗任何模型 Token** — 纯 HTTP 调用
- **不调用 WebSearch/SearXNG** — 数据源是东方财富
- **不进入知识库** — 不写入任何向量或知识表
- 失败降级返回空列表 + warn 日志，主流程不中断

---

## 三、前端实现

### 3.1 改造模态框搜索

**现状问题**：
- `stockOptions` 写死 3 条
- 搜索只是前端 `hidden` 过滤，没有真正的 API 调用
- 选择标的后只改显示，没有维护 `currentInstrument` 状态

**改造后**:

```
用户输入"茅台"
  ↓ 防抖 300ms
  ↓ GET /api/v1/stocks/lookup?keyword=茅台&limit=10
  ↓ 渲染为下拉列表:
     ┌──────────────────────────────────────┐
     │ [SH] 贵州茅台                        │
     │      600519 · A股                    │
     ├──────────────────────────────────────┤
     │ [ETF]消费ETF                         │
     │      159928 · 场内ETF                │
     ├──────────────────────────────────────┤
     │ [LOF]白酒基金LOF                     │
     │      161725 · LOF                    │
     ├──────────────────────────────────────┤
     │ [FD] 招商中证白酒A                   │
     │      012414 · 场外基金               │
     └──────────────────────────────────────┘
  ↓ 用户点击某一项
  ↓ 确定 currentInstrument
```

### 3.2 currentInstrument 状态管理

```javascript
// 全局状态
let currentInstrument = loadInstrumentFromStorage();

function loadInstrumentFromStorage() {
  try {
    const raw = localStorage.getItem('stockwise_instrument');
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveInstrumentToStorage(instrument) {
  if (instrument) {
    localStorage.setItem('stockwise_instrument', JSON.stringify(instrument));
  } else {
    localStorage.removeItem('stockwise_instrument');
  }
}

function selectInstrument(item) {
  currentInstrument = {
    symbol: item.code,
    assetType: item.assetType,
    name: item.name,
    market: item.market
  };
  saveInstrumentToStorage(currentInstrument);
  updateInstrumentCard(item);
  closeModal();
}

function clearInstrument() {
  currentInstrument = null;
  saveInstrumentToStorage(null);
  // 显示"未选择标的"状态
}
```

### 3.3 发送消息时携带 instrument

```javascript
async function sendMessage(message) {
  const body = {
    sessionId: currentSessionId,
    message: message,
    instrument: currentInstrument  // null 时后端走普通问答
  };

  const response = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });

  // 消费 SSE ReadableStream...
}
```

### 3.4 消息中的显式代码 vs 上下文标的

后端已经处理优先级：用户消息中直接写了 `000001` 则用它，没有写则用 `instrument.symbol`。

前端不需要做额外判断。用户输入"000001 呢"时，后端从消息提取到 `000001`，覆盖 `instrument.symbol`。前端 `currentInstrument` 保持不变（用户没切换标的，只是随口问了另一个）。

可选优化：后端在 SSE `done` 事件中返回实际使用的 `symbol`，前端据此判断是否需要提示用户切换：

```json
{
  "type": "done",
  "usedSymbol": "000001",        // 后端实际使用的标的
  "contextSymbol": "600519",     // 当前上下文标的
  "symbolConflict": true         // 消息中的代码与上下文不同
}
```

前端收到 `symbolConflict: true` 时，可以在消息区插入系统提示：
> "你提到了 000001，当前上下文标的仍是 600519。要切换吗？[切换]"

### 3.5 页面刷新恢复

```javascript
// 页面加载时
document.addEventListener('DOMContentLoaded', () => {
  const saved = loadInstrumentFromStorage();
  if (saved) {
    currentInstrument = saved;
    updateInstrumentCard(saved);
  } else {
    showEmptyState();  // "未选择标的，当前为普通问答模式"
  }
});
```

### 3.6 搜索 UX 细节

| 交互 | 行为 |
|------|------|
| 输入后防抖 | 300ms 无输入后发起请求 |
| 加载中 | 显示 spinning 动画 |
| 无结果 | "未找到匹配的标的，请尝试输入完整代码" |
| 网络错误 | "搜索暂时不可用，请直接输入 6 位代码" |
| 用户直接输入完整 6 位代码 | 前端直接设置 `currentInstrument`，不需要搜索 API |
| 键盘导航 | `↑` `↓` 选择候选，`Enter` 确认，`Esc` 关闭 |
| 最近选择 | localStorage 保存最近 5 个选过的标的，模态框打开时预展示 |

---

## 四、对接已有系统

### 4.1 与 ChatController 的关系

现有 `POST /api/v1/chat/stream` 已经接受 `ChatStreamRequest.instrument`：

```java
public record ChatStreamRequest(
    String sessionId,
    String message,
    ChatInstrument instrument   // ← 已有的字段
) {}

public record ChatInstrument(
    String symbol,
    String assetType
) {}
```

**不需要改后端请求结构**，只需要确保前端每次请求都填充这个字段。

### 4.2 与 RequestRouter 的关系

现有 `RequestRouter.route(question, contextSymbol)` 已经支持上下文标的：

```
instrument.symbol  →  contextSymbol
消息中的显式代码   →  explicitSymbol（正则提取，优先使用）
```

**不需要改路由逻辑**。

### 4.3 与 SessionState 的关系

`SessionState` 已有 `symbol` 字段。选股后可通过以下两种方式之一持久化：
- **方案 A（推荐）**: 不走后端，纯前端 localStorage，简单可靠
- **方案 B**: 加一个 `POST /api/v1/session/instrument` 写入 Redis SessionState

建议先实施方案 A，后续需要跨设备同步时补方案 B。

### 4.4 额外约束

- 标的搜索不消耗 Token，不进入 Agent Run 审计
- 不写入任何知识库表
- stock-wrapper 返回结果不缓存（标的搜索结果实时性要求不高，但首次实现先不引入缓存复杂度）
- 前端 `POST /api/v1/chat/stream` 请求中的完整用户问题不得出现在 URL（SSE 协议已保证使用 POST body）

---

## 五、测试要求

### 5.1 stock-wrapper lookup 端点测试

```bash
# 正常搜索
curl -X POST http://localhost:3001/lookup \
  -H "Authorization: Bearer $STOCK_WRAPPER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"keyword":"茅台","limit":5}'

# 预期: 返回 2-10 条结果，第一条为 600519 贵州茅台

# 无结果
curl ... -d '{"keyword":"xxxxxxxxx","limit":5}'
# 预期: 返回 items=[]

# 空关键词
curl ... -d '{"keyword":"","limit":5}'
# 预期: 返回 error
```

### 5.2 Java 后端测试

```bash
curl "http://localhost:8080/api/v1/stocks/lookup?keyword=沪深300&limit=8"
# 预期: 返回 510300、159919 等结构化列表
```

### 5.3 前端测试

- 输入"茅台" → 防抖后弹出候选列表
- 点击选择 → instrument-card 更新，localStorage 写入
- 刷新页面 → 标的恢复
- 输入完整 6 位代码 → 直接设置标的
- 点"暂不选择" → 清空标的 → 进入普通问答模式
- 发送消息 → 请求体包含 `instrument` 字段

---

## 六、不要做的事

- 不要用 SearXNG 做标的搜索
- 不要把 `lookup` 结果写入知识库
- 不要在 `lookup` 调用上消耗模型 Token
- 不要把 `lookup` 调用写入 Agent Run 审计
- 不要修改 `ChatStreamRequest` 的结构（已有 `instrument` 字段）
- 不要修改 `RequestRouter` 的路由逻辑（已有 `contextSymbol` 参数）
- 不要引入新的 Docker 服务

---

## 七、实现顺序

1. **stock-wrapper: 新增 `/lookup` 端点** — 调东方财富 API，返回标准化 JSON
2. **stockwise-backend: 新增 `GET /api/v1/stocks/lookup`** — Gateway + Controller
3. **前端: 模态框改造** — 接入 API、防抖、下拉渲染、键盘导航
4. **前端: currentInstrument 状态管理** — localStorage 持久化、刷新恢复
5. **前端: 消息发送携带 instrument** — 每次请求带 `currentInstrument`
6. **前端: instrument-card 实时渲染** — 选股后更新顶部卡片
7. **端到端验证** — 选股 → 发送问题 → 后端正确使用标的 → SSE 返回
