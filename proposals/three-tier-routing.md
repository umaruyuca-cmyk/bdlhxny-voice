# StockWise 三层路由决策与执行门禁重构方案

> **状态**：核心路由、执行计划与测试初版已实施，真实模型灰度和标注集校准待继续。  
> **用途**：用确定性规则处理高确定性请求，用 DeepSeek 补足自然语言语义分类，再由 Java 校验器生成最终可执行路由。  
> **核心原则**：Regex 只做快通道，DeepSeek 只生成候选分类，Java 拥有最终路由权，执行权限仍由固定策略和付费模型门禁控制。  
> **目标范围**：重构 `RequestRouter`、`RuleBasedRouteResolver` 和路由数据结构；新增板块分析 Route；调整 Route 到 Skill、WebSearch 和模型策略的映射。  
> **非目标**：不让模型自主选择工具、模型名称、API 地址或扩大 Route 权限；不修改 stock-analysis-skill 的确定性计算规则。

---

## 一、当前问题与重构目标

### 1.1 已知误判

| 用户输入 | 期望路由 | 当前路由 | 主要原因 |
|---|---|---|---|
| “科技板块最近的热度怎么样？” | `SECTOR_ANALYSIS` | `NEED_CLARIFICATION` | 缺少独立板块路由，模糊词被当成单标的问题 |
| “新能源车是不是到顶了？” | `SECTOR_ANALYSIS` | `NEED_CLARIFICATION` | 行业/概念实体和板块方向判断没有独立执行链 |
| “帮我看看我持仓的整体风险” | `PORTFOLIO_DECISION` | `NEED_CLARIFICATION` | 持仓意图规则覆盖不足 |
| “央行降息对银行股有什么影响？” | `MARKET_CAUSAL_ANALYSIS` | `KNOWLEDGE_QA` | 缺少“外部事件 + 市场主体 + 影响判断”的组合识别 |

### 1.2 根因

- 正则白名单适合识别代码、明确关键词和固定句式，不适合覆盖无限自然语言表达。
- 当前规则一旦返回 `RouteDecision`，后续分类器没有机会纠正误判。
- 现有 Route 缺少板块热度、排名、趋势和资金流分析的独立语义。
- `QUANT_DECISION` 同时承担 ETF 量化和板块排名，Route 与真实 Skill Command 的边界不清晰。
- 当前 `RouteDecision` 只有单个 `symbol`，无法表达多标的、板块类型和市场主体。
- 当前 `MARKET_CAUSAL_ANALYSIS` 固定执行 `stock + webSearch`，无法处理“银行股”等板块主体。
- `NEED_CLARIFICATION` 没有区分“模型不可用”和“语义本身不确定”，容易被低级兜底重新升级。

### 1.3 重构目标

1. 高确定性请求继续走免费、低延迟的 Regex 快通道。
2. Regex 无法唯一决定 Route 时，调用 DeepSeek 生成受限的 `RouteCandidate`。
3. DeepSeek 不直接生成最终 `RouteDecision`，Java 必须校验实体来源、Route 前置条件和执行权限。
4. 新增 `SECTOR_ANALYSIS`，并让它独占 `sector` command。
5. `QUANT_DECISION` 只负责至少两个 ETF/基金代码的量化比较与轮动。
6. 因果分析根据主体类型选择 `stock + webSearch` 或 `sector + webSearch`。
7. 路由分类付费调用和最终投资分析付费调用分别审计，不能互相冒充。
8. 路由模型超时、异常或关闭时安全降级，不阻断主对话，也不扩大执行权限。

---

## 二、架构原则

### 2.1 三层只负责“决定 Route”

```text
第一层：确定性实体抽取 + Regex 快通道
    ↓ ABSTAIN
第二层：DeepSeek 语义候选分类
    ↓ RouteCandidate
第三层：Java 确定性校验与规范化
    ↓ RouteDecision
```

`RouteExecutionPolicyRegistry`、`ExplicitAnalysisExecutor`、`BoundedReactLoop` 和 `PaidModelGate` 属于 Route 确定后的执行安全层，不计入三层路由。

### 2.2 模型只能提供候选，不能提供权限

DeepSeek 可以判断用户更像在问什么，但不能决定：

- 使用哪个模型或 API。
- 是否允许调用付费最终分析。
- 是否允许执行 `stock`、`portfolio`、`quant`、`sector` 或 `webSearch`。
- 是否跳过 Skill JSON 契约、数据时效或外部证据校验。
- 是否接受用户问题中不存在的股票代码或板块实体。

最终执行权始终来自：

```text
RouteDecision
→ RouteExecutionPolicyRegistry
→ ExecutionPlan
→ BoundedReactLoop
→ Skill/WebSearch 契约校验
→ PaidModelGate
```

### 2.3 路由分类与最终分析是两类付费调用

现有 `PaidModelGate` 要求先取得已校验的 Skill Observation，因此不适合直接承担前置路由分类门禁。

新增独立、用途固定的 `RoutingClassificationClient`：

- 只能使用固定系统 Prompt。
- 只能返回固定 JSON。
- 不注册任何工具。
- 不接收持仓、成本、预算、用户 ID 等隐私数据。
- 使用独立模型配置、Token 上限、超时和并发限制。
- 审计目的固定为 `ROUTING_CLASSIFICATION`。

最终投资分析仍只能通过：

```text
PaidAnalysisClient
→ PaidModelGate
→ purpose = FINAL_INVESTMENT_ANALYSIS
```

底层 `DeepSeekClient` 继续保持包内实现，不能重新暴露给任意业务组件。

---

## 三、目标流程

```text
用户问题 + 前端当前标的
    │
    ▼
InputGuardrail
    │
    ▼
DeterministicEntityExtractor
    │  输出：显式代码、当前标的、是否存在持仓、原始板块词
    ▼
RuleBasedRouteResolver
    ├─ MATCH   → RouteCandidate
    └─ ABSTAIN → RoutingClassificationClient
                     ├─ CLASSIFIED  → RouteCandidate
                     ├─ AMBIGUOUS   → NEED_CLARIFICATION
                     └─ UNAVAILABLE → 本地保守兜底
                                          │
                                          ▼
                              DeterministicRouteValidator
                                          │
                                          ▼
                                  RouteDecision
                                          │
                                          ▼
                           RouteExecutionPolicyRegistry
                                          │
                                          ▼
                              ExplicitAnalysisExecutor
                                          │
                                          ▼
                        BoundedReactLoop + Skill/WebSearch
                                          │
                                          ▼
                                  PaidModelGate
```

### 3.1 三种分类结果必须分开

| 分类状态 | 含义 | 后续处理 |
|---|---|---|
| `CLASSIFIED` | 模型给出了完整候选 Route | 进入 Java 确定性校验 |
| `AMBIGUOUS` | 问题语义本身不清晰 | 直接追问，不得再交给低级分类器覆盖 |
| `UNAVAILABLE` | 超时、网络异常、空响应、非法 JSON | 进入本地保守兜底；仍无法安全判断时追问 |

禁止使用以下流程：

```text
DeepSeek 返回 NEED_CLARIFICATION
→ IntentClassifier 再猜一次
→ 把不确定请求升级为分析 Route
```

---

## 四、Route 语义与执行边界

### 4.1 Route 定义

| Route | 语义 | 主体要求 | Skill Command | WebSearch | 最终模型 |
|---|---|---|---|---:|---|
| `GENERAL_CHAT` | 问候、闲聊、产品能力说明 | 无 | 无 | 否 | 本地 |
| `KNOWLEDGE_QA` | 概念、术语、计算方法、非时效规则 | 无 | 无，使用知识库 | 否 | 本地 |
| `EXTERNAL_RESEARCH` | 最新政策、公告、新闻、公开事实 | 可无金融主体 | 无 | 必须 | 本地 |
| `MARKET_FACT` | 价格、K 线、技术指标事实 | 单一代码 | `stock` | 否 | 固定模板 |
| `STOCK_DECISION` | 单标的买卖、仓位、风险和走势决策 | 单一代码 | `stock` | 默认否 | Skill 校验后付费 |
| `PORTFOLIO_DECISION` | 整体持仓、调仓、组合风险、月度分配 | 真实持仓存在 | `portfolio` | 默认否 | Skill 校验后付费 |
| `QUANT_DECISION` | 多 ETF/基金比较、轮动、目标权重 | 至少两个代码 | `quant` | 默认否 | Skill 校验后付费 |
| `SECTOR_ANALYSIS` | 行业/概念热度、排名、趋势、资金流和是否见顶 | 合法板块实体或整体排名目标 | `sector` | 默认否 | Skill 校验后付费 |
| `MARKET_CAUSAL_ANALYSIS` | 事件、政策、公告对股票、板块或市场的影响 | 单标的、板块或市场 | `stock` 或 `sector` | 必须 | Skill 与证据校验后付费 |
| `NEED_CLARIFICATION` | 意图、主体或必要参数不足 | 不满足执行条件 | 无 | 否 | 固定模板 |

### 4.2 `SECTOR_ANALYSIS` 取代 `SECTOR_OVERVIEW`

使用 `SECTOR_ANALYSIS`，不使用 `SECTOR_OVERVIEW`。原因是以下请求已经包含方向判断，不只是概览：

- “新能源车是不是到顶了？”
- “科技板块现在还能追吗？”
- “消费板块资金流入是真强还是高位分歧？”

该 Route 必须依据 `sector --json` 返回的确定性字段分析：

- 当日、5 日和已验证的 20 日变化。
- 主力资金流、换手或量能代理。
- `historyCoverage`、`heatScoreQuality` 和 `dataQuality.warnings`。
- `asOf`、`allowsDirectionalSignal`、`provisional`。
- `methodology.version` 和 `decisionBasis`。

未经验证的 5 日代理不能被付费模型改写为确定的方向性结论。

### 4.3 `QUANT_DECISION` 不再处理板块排名

`QUANT_DECISION` 只允许执行 `quant`：

```text
“510300 和 159915 哪个更强” → QUANT_DECISION
“科技和新能源车哪个板块更热” → SECTOR_ANALYSIS
```

从 `QUANT_DECISION` 的 Route 白名单中移除 `sector`，避免两个 Route 争抢同一命令。

### 4.4 `EXTERNAL_RESEARCH` 与 `MARKET_CAUSAL_ANALYSIS`

```text
“最新 LPR 是多少”              → EXTERNAL_RESEARCH
“最近有哪些降息政策”            → EXTERNAL_RESEARCH
“降息对银行股有什么影响”        → MARKET_CAUSAL_ANALYSIS
“某公告具体说了什么”            → EXTERNAL_RESEARCH
“某公告对 600519 的影响是什么”  → MARKET_CAUSAL_ANALYSIS
```

区分标准：

- 只查询最新外部事实：`EXTERNAL_RESEARCH`。
- 要求解释外部事件对市场主体的影响：`MARKET_CAUSAL_ANALYSIS`。

### 4.5 混合意图优先级

同一问题同时包含事实和决策时，选择能够覆盖全部必要数据的更强 Route：

| 输入 | 最终 Route | 原因 |
|---|---|---|
| “600519 现在多少钱，还能买吗？” | `STOCK_DECISION` | `stock` 同时提供行情事实和决策数据 |
| “159915 的 MACD 怎么样，适合加仓吗？” | `STOCK_DECISION` | 买卖决策优先于单纯指标事实 |
| “最新降息消息是什么，对银行股影响大吗？” | `MARKET_CAUSAL_ANALYSIS` | 外部事实与影响分析合并执行 |
| “比较 510300 和 159915，顺便给目标权重” | `QUANT_DECISION` | 多标的量化目标明确 |

---

## 五、路由数据结构

### 5.1 主体类型

```java
/**
 * 描述本轮分析所针对的市场主体，用于生成唯一且可校验的执行计划。
 */
public enum RouteSubjectType {
    NONE,
    STOCK,
    ETF_POOL,
    SECTOR,
    PORTFOLIO,
    MARKET
}
```

### 5.2 路由来源

```java
/**
 * 记录最终路由的判定来源，便于审计命中率、降级率和模型漂移。
 */
public enum RouteSource {
    REGEX,
    DEEPSEEK,
    LOCAL_FALLBACK,
    CLARIFICATION
}
```

### 5.3 确定性上下文

```java
/**
 * 保存由 Java 提取并校验的路由上下文，禁止模型重新生成代码和隐私字段。
 */
public record RoutingContext(
        String question,
        List<String> explicitSymbols,
        String contextSymbol,
        boolean portfolioAvailable
) {
}
```

规则：

- `explicitSymbols` 只由 Java 的 6 位代码正则提取。
- `contextSymbol` 必须先通过 6 位代码校验。
- 问题中的显式代码优先于前端当前标的。
- 不把持仓详情、成本、预算或历史回答发送给路由模型。

### 5.4 模型候选结果

```java
/**
 * 保存语义分类器的受限候选结果，必须经过 Java 校验后才能执行。
 */
public record RouteCandidate(
        RequestRoute route,
        RouteSubjectType subjectType,
        List<String> sectorMentions,
        String sectorType,
        boolean useContextSymbol,
        double reportedConfidence,
        String ambiguityReason,
        RouteSource source
) {
}
```

候选结果不包含任意 `symbols`。模型只能声明是否需要使用已校验的 `contextSymbol`；显式代码始终来自 `RoutingContext.explicitSymbols()`。

### 5.5 最终路由结果

```java
/**
 * 保存通过实体、语义和策略校验的最终执行路径，后续组件不得重新解释用户意图。
 */
public record RouteDecision(
        RequestRoute route,
        ChatIntent compatibleIntent,
        ModelPolicy modelPolicy,
        RouteSubjectType subjectType,
        List<String> symbols,
        List<String> sectors,
        String sectorType,
        String reasonCode,
        RouteSource routeSource,
        double confidence,
        boolean requiresMarketData,
        boolean requiresExternalEvidence,
        boolean needsClarification,
        String clarification
) {
    /**
     * 返回单标的 Route 的主代码，非单标的 Route 返回 null。
     */
    public String primarySymbol() {
        return symbols.size() == 1 ? symbols.get(0) : null;
    }
}
```

迁移现有 `decision.symbol()` 调用时统一改为 `decision.primarySymbol()`，多标的 Route 不得静默取第一个代码。

---

## 六、第一层：确定性实体抽取与 Regex 快通道

### 6.1 Resolver 返回 MATCH 或 ABSTAIN

Regex 规则不再使用统一 confidence 阈值，也不能因为存在 `symbol` 就自动认为意图明确。

```java
/**
 * 仅识别能够唯一决定 Route 的确定性句式，其他请求明确返回 ABSTAIN。
 */
public Optional<RouteCandidate> resolve(RoutingContext context) {
    // 1. 按固定优先级匹配高确定性规则。
    // 2. 无法唯一决定 Route 时返回 Optional.empty()。
}
```

禁止使用：

```java
decision.confidence() >= 0.8 || decision.symbol() != null
```

代码实体明确不等于用户意图明确。例如“帮我看看 600519”仍然应该进入语义分类或追问。

### 6.2 保留的高确定性规则

```text
问候、谢谢、帮助                         → GENERAL_CHAT
单一代码 + 明确价格/K线/指标事实词       → MARKET_FACT
单一代码或当前标的 + 明确买卖/仓位词     → STOCK_DECISION
明确“我的持仓/组合/整体仓位/调仓”        → PORTFOLIO_DECISION
至少两个代码 + ETF/基金比较或轮动词      → QUANT_DECISION
明确板块/行业/概念 + 热度/排名/资金流词   → SECTOR_ANALYSIS
最新/近期 + 政策/公告/新闻/消息查询       → EXTERNAL_RESEARCH
什么是/如何计算/区别/定义                → KNOWLEDGE_QA
```

### 6.3 必须 ABSTAIN 的模糊表达

```text
“怎么样”
“怎么看”
“分析一下”
“帮我看看 600519”
“新能源车有什么影响”
“这个还能不能上”
```

这些表达需要结合主体、上下文和目标判断，不能由单个宽泛正则直接决定 Route。

---

## 七、第二层：DeepSeek 语义候选分类

### 7.1 固定输入

发送给模型的用户消息使用结构化 JSON，不拼接持仓和会话历史：

```json
{
  "question": "央行降息对银行股有什么影响？",
  "explicitSymbols": [],
  "contextSymbolAvailable": false,
  "portfolioAvailable": true
}
```

`contextSymbol` 的具体值可以不发送；模型只需要判断当前问题是否引用“这只、它、当前标的”。实际代码仍由 Java 填入。

### 7.2 系统 Prompt

```text
你是 StockWise 的路由候选分类器。你只能判断语义，不能回答问题、提供投资建议或授权工具。

安全规则：
1. 只输出 JSON。
2. route 只能使用提供的枚举。
3. 不得生成、补全或猜测股票代码。
4. sectorMentions 只能摘录用户问题中出现的板块、行业或概念名称。
5. 语义不清、主体不足或存在多个冲突目标时，返回 NEED_CLARIFICATION。
6. reportedConfidence 只是分类器自评，系统不会仅凭该字段授权执行。

Route：
- GENERAL_CHAT：问候、闲聊、产品能力。
- KNOWLEDGE_QA：概念、术语、计算方法、非时效规则。
- EXTERNAL_RESEARCH：最新政策、公告、新闻和公开事实查询。
- MARKET_FACT：单标的价格、K线和指标事实。
- STOCK_DECISION：单标的买卖、仓位、风险和走势决策。
- PORTFOLIO_DECISION：整体持仓、调仓、组合风险和资金分配。
- QUANT_DECISION：至少两个ETF或基金的比较、轮动和目标权重。
- SECTOR_ANALYSIS：行业或概念的热度、排名、趋势、资金流和方向判断。
- MARKET_CAUSAL_ANALYSIS：外部事件对股票、板块或市场的影响。
- NEED_CLARIFICATION：意图、主体或必要参数不清晰。

输出示例：
{
  "route": "SECTOR_ANALYSIS",
  "subjectType": "SECTOR",
  "sectorMentions": ["新能源车"],
  "sectorType": "UNKNOWN",
  "useContextSymbol": false,
  "reportedConfidence": 0.92,
  "ambiguityReason": null
}
```

### 7.3 使用原生 JSON Output

调用 DeepSeek 时应设置 JSON Output，而不是只依靠截取第一个大括号：

```text
response_format = {"type": "json_object"}
max_tokens = 256
tools = []
```

仍需处理：

- 空 content。
- 输出被截断。
- 非法枚举。
- 缺少必填字段。
- 多余或冲突字段。
- `sectorMentions` 不来自原问题。
- 模型要求使用 context symbol，但上下文没有合法代码。

### 7.4 confidence 的定位

`reportedConfidence` 是模型自评，不等于真实准确率。

- 不能仅凭 `reportedConfidence >= 0.7` 放行 Route。
- Route 前置条件和实体来源校验始终优先。
- confidence 只用于审计、灰度和离线校准。
- 阈值必须基于标注语料的混淆矩阵确定，不能凭经验写死。

---

## 八、第三层：Java 确定性校验

### 8.1 校验矩阵

| Route | 确定性前置条件 | 不满足时 |
|---|---|---|
| `GENERAL_CHAT` | 不需要金融主体 | 正常放行 |
| `KNOWLEDGE_QA` | 不依赖实时市场事实 | 若包含“最新/现在”则改为外部研究或事实 Route |
| `EXTERNAL_RESEARCH` | 能生成受限 SearchTask | 无法提取公开检索目标时追问 |
| `MARKET_FACT` | 恰好一个合法代码 | 追问标的代码 |
| `STOCK_DECISION` | 恰好一个合法代码 | 追问标的代码或分析目标 |
| `PORTFOLIO_DECISION` | 当前用户存在真实持仓 | 执行层提示先维护持仓 |
| `QUANT_DECISION` | 至少两个不同合法代码 | 追问 ETF/基金池 |
| `SECTOR_ANALYSIS` | 至少一个可规范化板块实体，或明确请求整体板块排名 | 追问行业或概念名称 |
| `MARKET_CAUSAL_ANALYSIS` | 存在股票、板块或市场主体，并能生成外部搜索任务 | 主体不足时追问 |
| `NEED_CLARIFICATION` | 不执行任何能力 | 返回针对缺失字段的具体追问 |

### 8.2 symbol 来源校验

允许的 symbol 只能来自：

1. 用户问题中由 Java 提取的显式 6 位代码。
2. 已通过格式校验的前端当前标的。

禁止接受：

- 模型输出的任意 6 位代码。
- 公司简称到代码的模型猜测。
- 被用户 Prompt 注入要求添加的隐藏代码。

公司名称到代码的映射应由独立、可核验的证券搜索能力完成，不属于本次路由模型职责。

### 8.3 sector 来源与类型校验

`sectorMentions` 必须：

- 能在原始问题中找到原文或受控别名。
- 经过 `SectorEntityResolver` 规范化。
- 映射为 `industry` 或 `concept`。

初始版本不自动同时查询 industry 和 concept。无法唯一确定类型时优先使用受控别名表；仍不确定则追问用户，避免扩大 Skill 调用次数。

### 8.4 生成唯一执行计划

Java 根据最终 Route 和主体类型生成 `ExecutionPlan`：

```text
MARKET_FACT + STOCK
→ stock

STOCK_DECISION + STOCK
→ stock

PORTFOLIO_DECISION + PORTFOLIO
→ portfolio

QUANT_DECISION + ETF_POOL
→ quant

SECTOR_ANALYSIS + SECTOR
→ sector(type, limit)

MARKET_CAUSAL_ANALYSIS + STOCK
→ stock + webSearch

MARKET_CAUSAL_ANALYSIS + SECTOR
→ sector(type, limit) + webSearch

MARKET_CAUSAL_ANALYSIS + MARKET
→ sector(industry, boundedLimit) + webSearch
```

`RouteExecutionPolicyRegistry` 可以维护 Route 的最大能力集合，但 `ExecutionPlan` 必须进一步收紧到本轮唯一允许的 Action。

---

## 九、Skill 与执行层调整

### 9.1 Route 策略

```java
put(RequestRoute.SECTOR_ANALYSIS, new RouteExecutionPolicy(
        RequestRoute.SECTOR_ANALYSIS,
        ChatIntent.PORTFOLIO_ANALYSIS,
        ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
        Set.of("sector"),
        false,
        false
));
```

调整现有策略：

```text
QUANT_DECISION
allowedSkillCommands: ["quant"]

MARKET_CAUSAL_ANALYSIS
allowedSkillCommands: ["stock", "sector"]
webSearchAllowed: true
webSearchRequired: true
```

虽然因果 Route 的最大集合允许 `stock` 和 `sector`，单次 `ExecutionPlan` 只能根据 `subjectType` 选择其中一个。

### 9.2 扩展 sector Gateway

当前 Java Gateway 固定执行 `industry + limit=20`，无法可靠处理概念板块和未进入前 20 的指定板块。

目标接口：

```java
/**
 * 获取指定板块类型的结构化排名数据，供 Route 执行层做实体匹配和定性分析。
 */
String sector(String type, int limit);
```

执行约束：

- `type` 只允许 `industry` 或 `concept`。
- `limit` 使用配置上限，不能由模型任意填写。
- 指定板块未出现在返回结果时，不得由模型猜测热度。
- 必须校验 `schemaVersion`、`command`、`asOf` 和 `dataQuality`。
- 必须保留 `methodology.version` 和 `decisionBasis`。

### 9.3 `ExplicitAnalysisExecutor`

新增 `SECTOR_ANALYSIS` 分支，并改造因果分析分支：

```java
case SECTOR_ANALYSIS -> sectorAnalysis(
        skill, contextualPrompt, decision, runContext);

case MARKET_CAUSAL_ANALYSIS -> causalAnalysis(
        skill, contextualPrompt, rawQuestion, decision, runContext);
```

`sectorAnalysis` 的固定顺序：

```text
requireCommand("sector")
→ stockAnalysisGateway.sector(type, limit)
→ StockSkillContractValidator
→ 定位用户指定板块
→ 校验 dataQuality 与方向信号许可
→ PaidModelGate
→ PaidAnalysisClient
```

`causalAnalysis` 不再无条件调用 `stockAction(decision)`，而是读取 `ExecutionPlan` 选择 `stockAction` 或 `sectorAction`。

### 9.4 Route 对应 Prompt

当前系统通过兼容 `ChatIntent` 选择 `SkillDefinition`。将 `SECTOR_ANALYSIS` 映射为 `PORTFOLIO_ANALYSIS` 会误用“持仓组合分析师”Prompt。

建议增加按 `RequestRoute` 选择最终系统 Prompt 的能力：

```text
RoutePromptRegistry
├─ STOCK_DECISION          → 单标的分析 Prompt
├─ PORTFOLIO_DECISION      → 持仓组合 Prompt
├─ QUANT_DECISION          → ETF 量化 Prompt
├─ SECTOR_ANALYSIS         → 板块趋势与资金流 Prompt
└─ MARKET_CAUSAL_ANALYSIS  → 外部证据归因 Prompt
```

`compatibleIntent` 只保留兼容和会话记录用途，不再决定最终分析 Prompt 或工具权限。

---

## 十、RequestRouter 调度

```java
/**
 * 合并确定性规则、语义候选分类和 Java 校验，并返回唯一可执行的路由结果。
 */
public RouteDecision route(String question, String contextSymbol, boolean portfolioAvailable) {
    RoutingContext context = entityExtractor.extract(
            question, contextSymbol, portfolioAvailable);

    // 1. 高确定性规则命中后仍进入统一校验器。
    Optional<RouteCandidate> regexCandidate = ruleResolver.resolve(context);
    if (regexCandidate.isPresent()) {
        return routeValidator.validate(context, regexCandidate.get());
    }

    // 2. 语义分类器只生成候选，不直接生成最终 RouteDecision。
    ClassificationResult semantic = routingClassifier.classify(context);
    if (semantic.status() == ClassificationStatus.CLASSIFIED) {
        return routeValidator.validate(context, semantic.candidate());
    }
    if (semantic.status() == ClassificationStatus.AMBIGUOUS) {
        return routeValidator.clarification(
                context, semantic.ambiguityReason(), RouteSource.CLARIFICATION);
    }

    // 3. 只有分类器不可用时才进入本地保守兜底。
    RouteCandidate fallback = localFallback.classify(context);
    return routeValidator.validate(context, fallback);
}
```

### 10.1 本地兜底要求

- 本地分类器不能直接授权工具。
- 股票分析意图但目标不明确时必须追问。
- 解析异常不能回退为 `GENERAL_CHAT` 后直接回答金融问题。
- 本地兜底同样必须经过 `DeterministicRouteValidator`。
- `enabled=false` 与外部模型不可用使用同一条安全降级链。

---

## 十一、配置与运行时约束

```yaml
stockwise:
  routing:
    semantic:
      enabled: ${DEEPSEEK_ROUTER_ENABLED:true}
      model: ${DEEPSEEK_ROUTER_MODEL:deepseek-v4-flash}
      max-output-tokens: ${DEEPSEEK_ROUTER_MAX_TOKENS:256}
      total-timeout-ms: ${DEEPSEEK_ROUTER_TIMEOUT_MS:2500}
      max-concurrent-calls: ${DEEPSEEK_ROUTER_MAX_CONCURRENCY:8}
```

说明：

- `reportedConfidence` 当前只写入候选和审计，不提供尚未校准的运行时阈值配置。
- 当前不重试；若未来允许空响应重试，所有尝试必须共享同一个总 deadline。
- 路由模型不需要深度推理，优先使用低延迟模型；最终选型以标注集准确率和线上延迟为准。
- 需要增加并发隔离和熔断，防止路由分类耗尽最终分析调用资源。
- `timeout-ms=5000` 对前置路由过长，默认总预算先设为 2500ms，再根据 p95 数据调整。

### 11.1 成本统计

不在方案中写死人民币单价。价格会随模型、缓存命中和供应商调整变化。

线上按实际 usage 记录：

```text
routeInputTokens
routeOutputTokens
routeModel
cacheHit
routeClassificationCalls
regexHitRate
semanticFallbackRate
semanticErrorRate
monthlyRoutingCost
```

评估重点不只看 Token 成本，还要同时观察：

- 路由 p50、p95、p99 延迟。
- Regex 命中率。
- 语义分类调用率。
- `AMBIGUOUS` 比例。
- 非预期 Route 升级率。
- 最终用户纠正率。

---

## 十二、审计事件

### 12.1 路由候选

```json
{
  "stepType": "ROUTE_CANDIDATE",
  "routeSource": "DEEPSEEK",
  "candidateRoute": "SECTOR_ANALYSIS",
  "subjectType": "SECTOR",
  "reportedConfidence": 0.92,
  "ambiguityReason": null
}
```

### 12.2 确定性校验

```json
{
  "stepType": "ROUTE_VALIDATION",
  "accepted": true,
  "finalRoute": "SECTOR_ANALYSIS",
  "reasonCode": "VALID_SECTOR_ANALYSIS",
  "symbolCount": 0,
  "sectorCount": 1,
  "sectorType": "concept"
}
```

### 12.3 路由模型调用

```json
{
  "stepType": "MODEL_CALL",
  "modelTier": "PAID_ROUTING",
  "provider": "deepseek",
  "purpose": "ROUTING_CLASSIFICATION",
  "inputTokens": 210,
  "outputTokens": 48
}
```

### 12.4 最终分析模型调用

```json
{
  "stepType": "MODEL_CALL",
  "modelTier": "PAID",
  "provider": "deepseek",
  "purpose": "FINAL_INVESTMENT_ANALYSIS",
  "route": "SECTOR_ANALYSIS",
  "gateReason": "ALLOWED"
}
```

两类付费调用必须能在审计中明确区分。

---

## 十三、实施步骤

### Step 1：扩展路由领域模型

新增：

```text
RouteSubjectType.java
RouteSource.java
RouteCandidate.java
ClassificationStatus.java
ClassificationResult.java
RoutingContext.java
ExecutionPlan.java
```

修改：

```text
RequestRoute.java
RouteDecision.java
```

新增 `RequestRoute.SECTOR_ANALYSIS`，不新增 `SECTOR_OVERVIEW`。

### Step 2：新增确定性实体抽取与校验

新增：

```text
DeterministicEntityExtractor.java
DeterministicRouteValidator.java
SectorEntityResolver.java
ExecutionPlanFactory.java
```

所有 Regex、DeepSeek 和本地兜底结果统一经过同一个校验器。

### Step 3：收缩 `RuleBasedRouteResolver`

- 只保留能够唯一决定 Route 的规则。
- 返回 `RouteCandidate` 或 `ABSTAIN`。
- 删除“有代码就自动接受”的捷径。
- 增加持仓、板块和多 ETF 的高确定性规则测试。

### Step 4：新增固定用途的路由分类客户端

新增：

```text
com.stockwise.llm.RoutingClassificationClient
```

该类可以在 `com.stockwise.llm` 包内复用包级 `DeepSeekClient`，但只能暴露固定的 `classify(RoutingContext)` 能力，不能接受调用方自定义 system Prompt。

### Step 5：重构 `RequestRouter`

按以下顺序调度：

```text
实体抽取
→ Regex MATCH/ABSTAIN
→ DeepSeek RouteCandidate
→ Java RouteValidator
→ 本地不可用兜底
```

`AMBIGUOUS` 不进入本地覆盖流程。

### Step 6：调整 Route 策略

修改 `RouteExecutionPolicyRegistry`：

- 新增 `SECTOR_ANALYSIS → sector`。
- `QUANT_DECISION` 移除 `sector`。
- `MARKET_CAUSAL_ANALYSIS` 允许 `stock` 或 `sector`，且必须 WebSearch。

### Step 7：扩展 sector 调用契约

修改：

```text
StockAnalysisGateway.sector(String type, int limit)
HttpStockAnalysisGateway
StockTools
相关测试
```

stock-wrapper 已支持 `type=industry|concept` 与受限 `limit`，Java Gateway 不再固定写死 industry。

### Step 8：改造显式执行器

修改 `ExplicitAnalysisExecutor`：

- 新增 `SECTOR_ANALYSIS` 分支。
- `QUANT_DECISION` 只执行 quant。
- `MARKET_CAUSAL_ANALYSIS` 按 `ExecutionPlan` 选择 stock 或 sector。
- 所有方向判断继续校验 Skill JSON 契约和数据时效。

### Step 9：按 Route 选择最终 Prompt

新增 `RoutePromptRegistry`，或重构 `SkillRegistry` 支持按 `RequestRoute` 取 Prompt。

修改 `AgentOrchestrator`，使 `compatibleIntent` 不再决定最终分析 Prompt 和工具权限。

### Step 10：配置、审计与灰度

- 增加路由分类模型配置。
- 增加 `ROUTE_CANDIDATE`、`ROUTE_VALIDATION` 和路由模型调用审计。
- 支持按比例灰度开启语义分类。
- 保留 `DEEPSEEK_ROUTER_ENABLED=false` 的安全降级能力。

---

## 十四、测试策略

### 14.1 纯单元测试

`RoutingClassificationClientTest` 使用模拟原始模型输出，只验证：

- JSON Output 解析。
- 空响应。
- 非法枚举。
- 字段缺失。
- 非法 sectorType。
- 模型试图返回股票代码。
- timeout 与 provider 异常映射为 `UNAVAILABLE`。

这类测试不能证明语义分类准确率。

### 14.2 Route 校验测试

必须覆盖：

```text
有代码但目标不明确                     → 追问或进入语义分类
模型生成问题中不存在的板块             → 拒绝
模型要求 contextSymbol 但上下文为空     → 追问
MARKET_FACT 缺代码                     → 追问
QUANT_DECISION 少于两个代码            → 追问
SECTOR_ANALYSIS 无法确定板块类型        → 追问
因果分析股票主体                       → stock + webSearch
因果分析板块主体                       → sector + webSearch
DeepSeek AMBIGUOUS                     → 不调用本地分类器覆盖
DeepSeek UNAVAILABLE                   → 进入本地保守兜底
```

### 14.3 标注语料回归

建立版本化测试集，例如：

```text
src/test/resources/routing/golden-cases-v1.jsonl
```

初始至少包含 100 条，覆盖：

- 问候与帮助。
- 知识问答和时效外部事实。
- 单标的事实与决策。
- 多 ETF 量化。
- 行业和概念板块。
- 股票、板块和市场因果分析。
- 当前标的指代。
- 多意图混合问题。
- Prompt 注入和乱码。
- 应主动追问的问题。

验收指标：

```text
总体准确率
各 Route precision / recall
高风险误升级数
AMBIGUOUS 比例
Regex 命中率
DeepSeek 调用率
```

`reportedConfidence` 阈值必须根据该测试集校准。

### 14.4 真实模型集成测试

真实 DeepSeek 测试默认关闭，不能放入普通 `mvn test` 的稳定测试集合。

通过环境开关手动执行：

```text
DEEPSEEK_ROUTER_INTEGRATION_TEST=true
```

用于检查：

- 当前模型是否遵守 JSON Output。
- Prompt 或模型版本升级后的分类漂移。
- 实际 Token、延迟和空响应率。

---

## 十五、验收标准

1. 普通 `mvn test` 全部通过，且不依赖真实 DeepSeek 网络。
2. 以下问题得到稳定 Route：

| 输入 | Route | 执行计划 |
|---|---|---|
| “科技板块最近的热度怎么样？” | `SECTOR_ANALYSIS` | `sector` |
| “新能源车是不是到顶了？” | `SECTOR_ANALYSIS` | `sector` |
| “央行降息对银行股有什么影响？” | `MARKET_CAUSAL_ANALYSIS` | `sector + webSearch` |
| “帮我看看持仓整体风险” | `PORTFOLIO_DECISION` | `portfolio` |
| “510300 和 159915 哪个更强？” | `QUANT_DECISION` | `quant` |
| “600519 现在多少钱，还能买吗？” | `STOCK_DECISION` | `stock` |

3. “你好”“谢谢”“帮助”继续通过 Regex 免费走 `GENERAL_CHAT`。
4. “帮我看看 600519”不能仅因为有代码就直接进入付费分析。
5. DeepSeek 返回非法 JSON、空内容或超时时，不抛出未处理异常。
6. DeepSeek 返回 `AMBIGUOUS` 时，不调用本地 IntentClassifier 覆盖。
7. `DEEPSEEK_ROUTER_ENABLED=false` 时，使用 Regex + 本地保守兜底 + Java 校验。
8. `TEMPLATE_ONLY` 和 `LOCAL_ONLY` Route 对最终 `PaidAnalysisClient` 调用次数为零。
9. 路由分类产生的付费调用单独记录为 `PAID_ROUTING`，不能伪装成最终分析调用。
10. 所有 `PAID_AFTER_VALIDATED_SKILL` Route 只有在 Skill 契约、主体、时效和必要外部证据通过后才能调用最终付费模型。
11. 每个 Route 只能执行本轮 `ExecutionPlan` 允许的 Action。
12. 模型生成的问题外 symbol、sector 或工具名不能进入最终 `RouteDecision`。

---

## 十六、改动影响面

| 文件或组件 | 改动 |
|---|---|
| `RequestRoute.java` | 新增 `SECTOR_ANALYSIS` |
| `RouteDecision.java` | 支持主体、多代码、板块、来源和审计字段 |
| `RuleBasedRouteResolver.java` | 收缩为高确定性 MATCH/ABSTAIN |
| `RequestRouter.java` | 三层路由调度 |
| `RoutingClassificationClient.java` | 新增固定用途的 DeepSeek 候选分类 |
| `DeterministicEntityExtractor.java` | 新增代码和上下文实体抽取 |
| `DeterministicRouteValidator.java` | 新增最终 Route 校验 |
| `SectorEntityResolver.java` | 新增板块别名与 industry/concept 规范化 |
| `ExecutionPlanFactory.java` | 新增 Route 到本轮唯一 Action 计划 |
| `RouteExecutionPolicyRegistry.java` | 新增 sector Route，收缩 quant，扩展 causal |
| `StockAnalysisGateway.java` | sector 支持 type 和 limit |
| `HttpStockAnalysisGateway.java` | 透传受限 sector 参数 |
| `ExplicitAnalysisExecutor.java` | 新增 sector 分支，因果分析按主体执行 |
| `SkillRegistry` / `RoutePromptRegistry` | 最终 Prompt 改为按 Route 选择 |
| `AgentOrchestrator.java` | 传入持仓可用状态并使用 Route Prompt |
| `AgentRunService.java` | 增加候选、校验和路由模型审计 |
| `application.yml` / `.env.example` | 增加路由模型、超时、并发和开关配置 |

预计保持核心逻辑不变：

```text
BoundedReactLoop 的有界执行原则
PaidModelGate 的 Skill/时效/证据校验原则
StockSkillContractValidator 的 JSON 契约规则
web-search-wrapper 的固定搜索协议
stock-analysis-skill 的确定性计算方法
```

---

## 十七、风险与缓解

| 风险 | 缓解 |
|---|---|
| 路由模型超时或不可用 | 总 deadline、并发隔离、熔断、本地保守兜底 |
| JSON 为空或格式异常 | 原生 JSON Output + DTO 严格校验 + `UNAVAILABLE` |
| 模型自信但分类错误 | confidence 不直接授权，Java 前置条件校验，标注集校准 |
| 模型臆造代码或板块 | symbol 只来自 Java；sector 必须匹配原文和受控别名 |
| `SECTOR_ANALYSIS` 与 `QUANT_DECISION` 重叠 | sector 独占板块，quant 独占多 ETF |
| 因果分析没有单一股票代码 | 通过 subjectType 选择 sector 或 stock |
| 路由分类绕过付费安全边界 | 独立固定用途客户端与审计；最终分析仍经 PaidModelGate |
| 付费分类增加延迟 | Regex 快通道、轻量模型、2500ms 总预算、p95 观测 |
| 价格变化导致成本估算失真 | 不写死单价，按实际 usage 与供应商账单统计 |
| Route 新增后误用旧 Portfolio Prompt | 最终系统 Prompt 改为按 RequestRoute 选择 |

---

## 十八、建议实施顺序

1. 先完成 Route 语义、数据结构、实体校验和单元测试。
2. 收缩 Regex，并建立首版标注语料。
3. 接入 `RoutingClassificationClient`，但先只做 shadow 分类，不影响线上 Route。
4. 对比 Regex、旧 Intent 和 DeepSeek 候选的混淆矩阵。
5. 完成 `SECTOR_ANALYSIS`、sector type 参数和 Route Prompt。
6. 改造因果分析的 stock/sector 动态执行计划。
7. 灰度启用 DeepSeek 候选分类。
8. 根据准确率、误升级数、延迟和成本调整阈值与模型。
9. 指标稳定后移除重复、失效的旧 Intent 路由职责。

最终目标不是让 DeepSeek 替代规则，而是形成明确分工：

```text
Regex 负责确定性
DeepSeek 负责语义候选
Java 负责信任边界
Policy 负责执行权限
Skill 负责事实与计算
PaidModelGate 负责最终分析放行
```

---

## 十九、双模式业务入口与三条稳定执行路径

前端对话入口拆分为 `general` 和 `stock` 两种模式。模式是服务端信任边界，不能再仅根据用户文本或模型分类决定是否进入股票分析。

| 前端模式 | 对外业务 Route | 允许能力 | 硬约束 |
|---|---|---|---|
| `general` | `DIRECT_CHAT` | DeepSeek 普通回答 | 不调用搜索、行情和股票 Skill |
| `general` | `TOOL_AGENT` | 有界 ReAct + SearXNG | 只允许 WebSearch，必须保留来源 |
| `stock` | `STOCK_ANALYSIS` | 原有细分 Route 与 Stock Skill | 必须先提交结构化 `instrument` |

### 19.1 请求协议

```json
{
  "sessionId": "client-session-id",
  "mode": "general",
  "message": "搜索一下今天的重要科技新闻",
  "instrument": null
}
```

- `mode=general` 时，服务端主动清除 `instrument`，避免股票上下文污染普通问答。
- `mode=stock` 且没有 `instrument` 时，返回 `NEED_INSTRUMENT`，不得从问题文本猜测代码后继续。
- 相同客户端 `sessionId` 按模式生成不同服务端会话键，普通问答和股票分析不共享 Redis 工作状态。
- 旧客户端未传 `mode` 时，只根据是否存在结构化 `instrument` 做兼容推断。

### 19.2 普通问答分流

普通问答不再进入股票三层分类。Java 先执行确定性判定：

```text
需要最新信息、搜索、核验、来源或链接
  -> TOOL_AGENT
其他普通问题
  -> DIRECT_CHAT
```

即使普通问题中出现六位股票代码，也只能留在 `DIRECT_CHAT` 或 `TOOL_AGENT`。只有用户切换到 Stock Agent 并选择标的，才允许进入 `STOCK_ANALYSIS`。

### 19.3 SSE 展示协议

前端只依赖稳定业务阶段，不直接展示内部模型供应商和成本策略：

| `status.step` | 含义 |
|---|---|
| `classifying` | 识别需求 |
| `direct_chat` | 直接回答 |
| `react_planning` | 规划搜索工具 |
| `searching_web` | 调用 SearXNG |
| `reading_sources` | 整理搜索来源 |
| `stock_validating` | 校验股票分析标的与权限 |

`agent_run` 和 `done` 同时返回对外 `route`、内部 `internalRoute`、`mode` 与 `runId`，兼顾前端稳定展示和后端审计。

### 19.4 Stock Agent 的单标的 Route 收缩

选择标的后，`instrument.symbol` 是本工作区唯一可信主体。用户文字只能描述分析目标，不能静默切换分析对象。

| Stock Agent 输入 | 处理 |
|---|---|
| 闲聊、问候、工作站使用问题 | `GENERAL_CHAT`，直接回答，不调用股票 Skill |
| 投资概念 | `KNOWLEDGE_QA`，不执行标的分析 |
| 最新新闻、公告与外部核验 | `EXTERNAL_RESEARCH`，只调用 WebSearch |
| 行情、指标与技术事实 | `MARKET_FACT`，只分析已选标的 |
| 买卖、仓位与风险决策 | `STOCK_DECISION`，只分析已选标的 |
| 事件对已选标的的影响 | `MARKET_CAUSAL_ANALYSIS`，只分析已选标的 |
| 文字中出现另一个六位代码 | `NEED_CLARIFICATION`，提示先切换标的 |
| 持仓组合、多标的比较或板块分析 | `NEED_CLARIFICATION`，提示进入未来对应工作区 |

这不是新增更多内部 Route，而是在 `routeStock` 入口对现有 Route 做上下文白名单收缩。这样可以保留原有执行器，同时防止单标的页面误入组合、量化或板块能力。

### 19.5 对话完成与知识沉淀解耦

每轮回答完成后直接返回 `COMPLETED`，会话状态恢复为 `idle`，用户可以立即继续提问。主流程不再自动执行：

```text
询问是否解决
  -> 抽取知识候选
  -> 再次确认是否入库
```

知识库继续作为后台检索和后续人工沉淀能力存在，但不再占用右侧主工作区，也不阻塞普通问答或 Stock Agent 连续追问。右侧统一改为“运行追踪”，用于展示 Route、ReAct、工具调用、模型门禁和最终回答。
