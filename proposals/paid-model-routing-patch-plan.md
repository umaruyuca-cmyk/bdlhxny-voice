# 付费分析模型路由修补方案（实施记录）

> 状态：代码修补及云端部署完成；2026-07-30 临时改用公网 IP 的 3001/3002 端口后，两套 Java Gateway 真实测试与 76 个全量测试均通过。  
> 边界：本文继续保留在 `proposals`，不作为 PRD、开发 Prompt 或正式架构真源。

## 1. 修补目标

建立一个代码层不可绕过的付费模型闸门：

```text
普通闲聊、投资知识问答、外部信息查询
→ 本地模型

股价、涨跌幅、日 K 展示
→ stock-analysis-skill + 固定模板

买卖、仓位、风险、组合、轮动、涨跌原因综合判断
→ stock-analysis-skill 成功并通过契约/时效校验
→ 才允许调用付费分析模型
```

“调用 Skill”只是付费模型的必要条件，不是充分条件。只查价格或日 K 即使调用了 Skill，也不使用付费模型。

## 2. 当前代码问题

### 2.1 所有主对话都会进入付费模型

`AgentOrchestrator.streamAndFinalize()` 当前统一调用：

```java
deepSeekClient.streamChatWithTools(...)
```

因此 `GENERAL_CHAT`、`INVESTMENT_QA`、`STOCK_ANALYSIS`、`PORTFOLIO_ANALYSIS` 最终都会消耗付费 Token。空工具白名单只能阻止工具越权，不能阻止付费模型调用。

### 2.2 当前四类意图无法区分“查数据”和“要决策”

`STOCK_ANALYSIS` 同时可能表示：

- “600519 现在多少钱”
- “展示 600519 最近 60 天日 K”
- “600519 现在能买吗”

前两类不需要付费推理，第三类才需要。

### 2.3 知识抽取存在隐藏的二次付费调用

用户回复“已解决”后，`KnowledgeExtractor` 会再次调用 `DeepSeekClient.call()`。即使原问题由本地模型回答，也会在知识抽取阶段产生付费 Token。

### 2.4 SearXNG 已部署，但共享搜索服务尚未抽取

SearXNG 公网实例已经完成部署和基础验证，当前确认百度、360 搜索可以返回中文结果；Bing 暂无结果，搜狗会触发 CAPTCHA。现阶段应将百度和 360 搜索作为默认上游，不把暂时不可用的搜索源纳入生产调用。

SearXNG 只是搜索引擎聚合器，不能直接作为每个 Agent 的业务接口。为避免 StockWise 与其他 Agent 重复实现鉴权、结果清洗和 Provider 适配，本方案新增独立的共享 `web-search-wrapper` 服务。

完整 WebSearch 能力目前还缺少以下模块：

- 用户需求到固定 `SearchTask` 的本地拆解。
- 查询内容的隐私、用途和数量校验。
- 独立 `web-search-wrapper` 的 Agent 鉴权、配额和请求契约。
- Wrapper 到 SearXNG 的 Provider 调用。
- SearXNG 原始结果到固定 `List<SearchResult>` 的清洗、去重和标准化。
- 来源去重、内容清理、提示词注入防护和证据充分性判断。
- 超时、熔断、审计及失败降级。

这些模块完成前，Agent 仍不得声称已经联网查询。SearXNG 和 `web-search-wrapper` 都不承担需求理解、答案生成或模型路由职责。

## 3. 新的路由模型

### 3.1 请求路由

```java
public enum RequestRoute {
    GENERAL_CHAT,
    KNOWLEDGE_QA,
    EXTERNAL_RESEARCH,
    MARKET_FACT,
    STOCK_DECISION,
    PORTFOLIO_DECISION,
    QUANT_DECISION,
    MARKET_CAUSAL_ANALYSIS,
    NEED_CLARIFICATION
}
```

### 3.2 模型策略

```java
public enum ModelPolicy {
    TEMPLATE_ONLY,
    LOCAL_ONLY,
    PAID_AFTER_VALIDATED_SKILL
}
```

### 3.3 固定路由结果

```java
public record RouteDecision(
        RequestRoute route,
        ModelPolicy modelPolicy,
        String symbol,
        String reasonCode,
        double confidence,
        boolean requiresMarketData,
        boolean requiresExternalEvidence,
        boolean needsClarification,
        String clarification
) {
}
```

本地模型只能选择枚举和填写受限字段，无权提供模型名称、API 地址、工具实现或付费开关。

### 3.4 固定搜索任务

用户原始描述不得直接发送给 `web-search-wrapper` 或 SearXNG。由各 Agent 自己的本地编排器先拆解为最多三个固定搜索任务：

```java
public enum SearchPurpose {
    NEWS_CATALYST,
    COMPANY_ANNOUNCEMENT,
    POLICY_UPDATE,
    KNOWLEDGE_VERIFY
}
```

```java
public record SearchTask(
        String taskId,
        SearchPurpose purpose,
        String query,
        String symbol,
        Integer freshnessDays,
        List<String> preferredDomains,
        Integer maxResults
) {
}
```

这是 StockWise 领域对象，其中 `symbol` 和 `SearchPurpose` 不进入共享协议。`HttpWebSearchGateway` 必须把它转换成不含股票私有字段的通用 `WebSearchTask`；其他 Agent 可以定义自己的领域任务，再转换成同一通用协议。

约束如下：

- `query` 只能包含检索所需的标的、事件、时间和公开限定词。
- 用户 ID、持仓、成本、预算、手机号、会话历史不得进入查询。
- 单次请求最多三个 `SearchTask`，每个任务最多保留五条结果。
- 当前价格、K 线、技术指标不得进入 WebSearch，必须路由到 `stock-analysis-skill`。
- 公司公告优先增加巨潮资讯或交易所官网域名限定；监管政策优先限定证监会等官方域名。
- `SearchPurpose`、时间范围、域名白名单由代码校验，本地模型不能输出任意工具参数。

### 3.5 固定搜索结果

SearXNG 原始响应只允许在 `web-search-wrapper` 内部出现，各 Agent 永远只接收：

```java
public record SearchResult(
        String resultId,
        String taskId,
        SearchPurpose purpose,
        String title,
        String url,
        String domain,
        String snippet,
        String sourceType,
        String provider,
        Instant publishedAt,
        Instant retrievedAt,
        Double relevanceScore
) {
}
```

标准化阶段必须执行：

- 仅保留 HTTP/HTTPS URL，并优先保留 HTTPS。
- 规范化 URL 后去重，移除跟踪参数和重复页面。
- 清理 HTML、控制字符、脚本内容和疑似提示词注入文本。
- 限制标题和摘要长度，不把完整网页正文直接送入模型。
- 标记官网、监管、交易所、主流媒体、普通网页等来源类型。
- 记录检索时间；无法确认发布时间时保持 `publishedAt=null`，禁止模型伪造日期。
- 同一条结果只能作为外部证据，不能覆盖 Skill 返回的确定性行情事实。

### 3.6 Route、Intent、Skill 的职责边界

三者不是同一个概念，也不是一一对应关系：

| 层级 | 回答的问题 | 是否具有最终执行权 |
|---|---|---:|
| `ChatIntent` | 用户大致在谈什么领域 | 否，只是兼容现有分类和提供路由信号 |
| `RequestRoute` | 本轮具体要走哪条执行链 | 是，决定工具、模型策略和付费门禁 |
| Skill/Command | 用哪个确定性能力取得数据 | 否，只能在 Route 授权后执行 |

正确关系为：

```text
用户输入
→ 确定性规则 + 本地 Intent 分类
→ RequestRouter
→ RouteDecision
→ 显式选择 Skill Command / WebSearch / RAG / 本地模型
→ PaidModelGate
```

Intent 不能直接决定付费模型，也不能直接授权工具。最终执行必须以 `RouteDecision` 为准。

### 3.7 当前 Intent 到 SkillDefinition 的兼容关系

现有代码只有四个 `ChatIntent`，`SkillRegistry` 当前映射如下：

| 当前 `ChatIntent` | 当前 `SkillDefinition` | 当前允许工具 |
|---|---|---|
| `GENERAL_CHAT` | `general-chat` | 无 |
| `INVESTMENT_QA` | `investment-knowledge-qa` | `searchInvestmentKnowledge` |
| `STOCK_ANALYSIS` | `stock-deep-analysis` | `analyzeStock` |
| `PORTFOLIO_ANALYSIS` | `portfolio-analysis` | `analyzePortfolio`、`analyzeQuant` |

这个映射只能作为迁移期兼容信息，不能继续承担最终编排。主要原因是：

- `STOCK_ANALYSIS` 无法区分查价格、看 K 线、买卖决策和涨跌归因。
- `INVESTMENT_QA` 无法区分本地知识库问答和需要联网的外部资料查询。
- `PORTFOLIO_ANALYSIS` 无法区分持仓调整和 ETF/板块量化轮动。
- 当前选中一个 SkillDefinition 后会把工具交给模型自主选择，不能形成代码层付费门禁。

### 3.8 目标 Route-Intent-Skill 映射

`stock-analysis-skill` 是一个真实 Skill，内部只有 `stock`、`portfolio`、`quant`、`sector` 四个白名单命令。当前价格和 K 线都复用 `stock` 命令的结构化输出，不新增 Quote Skill、Kline Skill 等虚构能力。

| `RequestRoute` | 兼容期 `ChatIntent` | SkillDefinition/能力 | 真实 Skill Command | WebSearch | 最终回答 |
|---|---|---|---|---:|---|
| `GENERAL_CHAT` | `GENERAL_CHAT` | 无金融 Skill | 无 | 否 | 本地模型 |
| `KNOWLEDGE_QA` | `INVESTMENT_QA` | `investment-knowledge-qa` / PgVector | 无 | 否 | RAG + 本地模型 |
| `EXTERNAL_RESEARCH` | `INVESTMENT_QA` | 无金融 Skill，使用 `WebSearchGateway` | 无 | 是 | 本地模型 |
| `MARKET_FACT` | `STOCK_ANALYSIS` | `stock-analysis-skill` | `stock` | 否 | 固定模板/前端 JSON |
| `STOCK_DECISION` | `STOCK_ANALYSIS` | `stock-analysis-skill` | `stock` | 默认否 | Skill 校验后付费模型 |
| `PORTFOLIO_DECISION` | `PORTFOLIO_ANALYSIS` | `stock-analysis-skill` | `portfolio`，必要时受控补充 `stock` | 默认否 | Skill 校验后付费模型 |
| `QUANT_DECISION` | `PORTFOLIO_ANALYSIS` | `stock-analysis-skill` | ETF 轮动用 `quant`；板块排名用 `sector` | 默认否 | Skill 校验后付费模型 |
| `MARKET_CAUSAL_ANALYSIS` | `STOCK_ANALYSIS` | `stock-analysis-skill` + `WebSearchGateway` | `stock` | 是，必须 | Skill 与证据双校验后付费模型 |
| `NEED_CLARIFICATION` | 任意初判 Intent | 无 | 无 | 否 | 固定追问/本地模型 |

补充规则：

- 表中的“兼容期 Intent”只用于复用当前分类器和审计字段，不能调用旧 `SkillRegistry.get(intent)` 后直接进入模型。
- `GENERAL_CHAT`、`EXTERNAL_RESEARCH`、`NEED_CLARIFICATION` 不应加载金融 Skill。
- `KNOWLEDGE_QA` 的 PgVector 检索是内部知识能力，不属于 `stock-analysis-skill`。
- `EXTERNAL_RESEARCH` 的 `WebSearchGateway` 是共享外部证据能力，不属于 `stock-analysis-skill`。
- `MARKET_CAUSAL_ANALYSIS` 是一个 Route 同时编排 Skill 和 WebSearch 的典型场景，不能降级成某个单一 Skill 自主执行。
- `sector` 只处理行业/概念板块排名；ETF 池轮动继续使用 `quant`，两者不能混用。
- `NEED_CLARIFICATION` 必须短路所有工具和付费模型，即使初判 Intent 是分析类。

### 3.9 映射的代码表达

映射必须由代码维护，不能只存在于 Prompt：

```java
public record RouteExecutionPolicy(
        RequestRoute route,
        ChatIntent compatibleIntent,
        ModelPolicy modelPolicy,
        List<String> allowedSkillCommands,
        boolean webSearchAllowed,
        boolean webSearchRequired
) {
}
```

示例：

```java
MARKET_FACT
→ compatibleIntent = STOCK_ANALYSIS
→ modelPolicy = TEMPLATE_ONLY
→ allowedSkillCommands = ["stock"]
→ webSearchAllowed = false
→ webSearchRequired = false
```

```java
MARKET_CAUSAL_ANALYSIS
→ compatibleIntent = STOCK_ANALYSIS
→ modelPolicy = PAID_AFTER_VALIDATED_SKILL
→ allowedSkillCommands = ["stock"]
→ webSearchAllowed = true
→ webSearchRequired = true
```

`ExplicitAnalysisExecutor` 在执行任何命令前必须同时校验：

```text
Route 允许该 Command
∧ Command 与请求目标一致
∧ 标的和资产类型合法
∧ 本轮工具预算未超限
```

不再允许“Intent 选 SkillDefinition，模型再从 Skill 工具列表中自由决定命令”的隐式路径。

## 4. 路由判断顺序

### 4.1 确定性规则优先

规则命中后不再让本地模型改写路由。

| 用户目标 | 示例 | 路由 | 模型 |
|---|---|---|---|
| 普通闲聊 | “你好” | `GENERAL_CHAT` | 本地 |
| 知识解释 | “什么是 MACD” | `KNOWLEDGE_QA` | 本地 |
| 外部事实 | “最新印花税政策” | `EXTERNAL_RESEARCH` | 本地 |
| 行情事实 | “600519 现在多少钱” | `MARKET_FACT` | 模板 |
| 日 K 展示 | “看最近60天K线” | `MARKET_FACT` | 模板/前端 |
| 单标的决策 | “600519 能买吗” | `STOCK_DECISION` | Skill 校验后付费 |
| 持仓决策 | “我的仓位怎么调” | `PORTFOLIO_DECISION` | Skill 校验后付费 |
| 量化决策 | “ETF轮动选哪只” | `QUANT_DECISION` | Skill 校验后付费 |
| 涨跌原因 | “600519 为什么突然跌” | `MARKET_CAUSAL_ANALYSIS` | Skill + WebSearch 后付费 |

“分析”一词不作为付费依据。“分析一下 MACD”“分析一下最新政策”仍然走本地模型。

### 4.2 本地模型只处理规则未覆盖的问题

Ollama 输出固定 JSON。若 `confidence < 0.80`、标的缺失或目标不明确，路由统一变为 `NEED_CLARIFICATION`。

典型追问：

```text
你是想查看当前行情，还是需要买卖和仓位建议？
```

追问阶段不调用 Skill，不调用付费模型。

## 5. 付费模型硬闸门

新增唯一入口 `PaidModelGate`：

```java
public PaidModelPermit evaluate(RouteDecision decision,
                                SkillObservation observation,
                                EvidenceBundle evidenceBundle) {
    boolean allowed =
            decision.modelPolicy() == ModelPolicy.PAID_AFTER_VALIDATED_SKILL
            && isPaidRoute(decision.route())
            && observation != null
            && observation.success()
            && observation.contractValidated()
            && observation.commandMatchesRoute()
            && observation.subjectMatches()
            && observation.freshnessValidated()
            && externalEvidenceSatisfied(decision, evidenceBundle);
    return new PaidModelPermit(allowed, allowed ? "ALLOWED" : rejectionReason(...));
}
```

允许付费的路由只有：

```text
STOCK_DECISION
PORTFOLIO_DECISION
QUANT_DECISION
MARKET_CAUSAL_ANALYSIS
```

任何其他服务不得直接注入或调用 `DeepSeekClient`。

其中 `externalEvidenceSatisfied()` 的规则为：

- `STOCK_DECISION`、`PORTFOLIO_DECISION`、`QUANT_DECISION` 默认不强制 WebSearch。
- `MARKET_CAUSAL_ANALYSIS` 必须同时取得已校验的行情 Skill Observation 和充分的外部证据。
- 因搜索超时、无结果、只有单一低质量来源或证据时间不匹配而不充分时，禁止付费模型调用。
- 外部证据不足时可由本地模型说明“当前无法可靠归因”，但不得编造原因。

## 6. 修补后的显式执行链

### 6.1 普通闲聊

```text
规则/本地分类
→ GENERAL_CHAT
→ LocalAnswerClient
→ SSE
```

### 6.2 投资知识问答

```text
KNOWLEDGE_QA
→ PgVector 检索
→ 过滤证据
→ LocalAnswerClient
→ SSE
```

### 6.3 当前价格和日 K

当前本地没有独立 Quote/Kline Skill，统一使用现有 `stock-analysis-skill stock` 命令：

```text
MARKET_FACT
→ StockAnalysisGateway.stock()
→ StockSkillContractValidator
→ 从 data.quote 或 data.history 提取
→ MarketFactResponder 固定模板/JSON
→ SSE
```

不进入 DeepSeek。

### 6.4 单标的深度分析

```text
STOCK_DECISION
→ 校验标的
→ StockAnalysisGateway.stock()
→ StockSkillContractValidator
→ PaidModelGate
→ DeepSeekClient.streamChat()（不再让付费模型自主选择工具）
→ SSE
```

### 6.5 外部资料查询

```text
EXTERNAL_RESEARCH
→ LocalSearchPlanner
→ List<SearchTask>
→ SearchPolicyValidator
→ HttpWebSearchGateway
→ web-search-wrapper
→ List<SearchResult>
→ EvidenceValidator
→ LocalAnswerClient
→ SSE
```

该路径只使用本地模型整理搜索结果，不调用付费模型。`web-search-wrapper` 接收固定搜索任务，SearXNG 只接收经过校验的搜索词；两者都不接收用户完整问题，也不负责生成最终答案。

### 6.6 行情涨跌原因分析

```text
MARKET_CAUSAL_ANALYSIS
├→ StockAnalysisGateway.stock()
│  → StockSkillContractValidator
└→ LocalSearchPlanner
   → SearchPolicyValidator
   → HttpWebSearchGateway
   → web-search-wrapper
   → List<SearchResult>
   → EvidenceValidator
       ↓
PaidModelGate
→ DeepSeekClient.streamChat()
→ SSE
```

只有行情数据和外部证据两条分支都通过校验，才能进入付费模型。付费模型只消费已校验的 Skill Observation 和固定 `List<SearchResult>`，不能自行重新搜索或修改查询。

### 6.7 共享 web-search-wrapper 调用契约

所有 Agent 只调用共享 Wrapper，不直接调用 SearXNG：

```text
POST {endpointUrl}
X-Agent-Id: ${WEB_SEARCH_AGENT_ID}
X-Search-Token: ${WEB_SEARCH_AGENT_TOKEN}
X-Request-Id: <requestId>
Content-Type: application/json
```

请求体：

```json
{
  "schemaVersion": "1.0",
  "tasks": [
    {
      "taskId": "task-001",
      "purposeCode": "COMPANY_ANNOUNCEMENT",
      "mode": "GENERAL",
      "query": "贵州茅台 2026 半年报",
      "language": "zh-CN",
      "freshnessDays": 30,
      "includeDomains": ["cninfo.com.cn"],
      "excludeDomains": [],
      "maxResults": 5
    }
  ]
}
```

响应体：

```json
{
  "schemaVersion": "1.0",
  "requestId": "request-001",
  "provider": "searxng",
  "results": [
    {
      "resultId": "result-001",
      "taskId": "task-001",
      "purposeCode": "COMPANY_ANNOUNCEMENT",
      "title": "贵州茅台相关公告",
      "url": "https://example.com/notice",
      "domain": "example.com",
      "snippet": "公告摘要",
      "sourceType": "OFFICIAL",
      "provider": "searxng",
      "publishedAt": null,
      "retrievedAt": "2026-07-28T10:00:00Z",
      "relevanceScore": 0.8
    }
  ],
  "errors": []
}
```

配置要求：

- 每个 Agent 使用独立的 `agentId + token`，不得共用一个全局 Token。
- `baseUrl`、Agent ID 和 Token 只从环境变量读取，真实 Token 不进入 Git、前端、日志或文档。
- Wrapper 只接受版本化通用协议；`schemaVersion` 不兼容时直接拒绝。
- `mode` 只允许 `GENERAL`、`NEWS`，`purposeCode` 是调用方提供的受限审计标签，只允许大写字母、数字和下划线。
- Wrapper 校验任务数量、查询长度、语言、域名、时间范围和结果上限。
- 股票代码、持仓、成本等领域字段不属于 Wrapper 协议，发送后必须因未知字段被拒绝。
- Wrapper 负责调用 SearXNG、清洗、去重、标准化、超时、受控重试、熔断和 Provider 降级。
- 各 Agent 负责本领域的 SearchTask 规划、隐私字段剔除、Route 判断和证据充分性校验。
- 前端不得直接调用 Wrapper 或 SearXNG，避免暴露 Token 和绕过 Agent 编排器。
- 公网只开放 Wrapper 的 `/api/search` 和必要健康检查；SearXNG 原始 `/search`、`/config` 不再向公网开放。
- 上游搜索引擎属于不稳定外部依赖；单个引擎失败不能转化为虚构结果。

### 6.8 搜索失败和降级

```text
百度和360均失败
→ 返回 SEARCH_PROVIDER_UNAVAILABLE
→ 本地模型明确告知外部资料暂不可用
→ 不调用付费模型
```

未来可以在 Wrapper 内增加 `BochaSearchProvider` 作为国内商业 API 降级源，但必须继续复用相同 `SearchTask` 和 `SearchResult`，业务 Agent 不得感知 Provider 原始结构。

### 6.9 共享服务边界与复用方式

```text
StockWise Agent ───────┐
新闻分析 Agent ────────┼→ web-search-wrapper
其他业务 Agent ────────┘   ├→ SearxngSearchProvider → SearXNG → 百度/360
                            └→ BochaSearchProvider（未来降级）
```

`web-search-wrapper` 是独立 Docker 服务，不是大模型、不是 Skill，也不包含任何 Agent 的业务 Intent。它只负责：

- 调用方身份认证和独立配额。
- 固定 `SearchTask` 请求校验。
- 搜索 Provider 选择和故障降级。
- 结果清洗、URL 规范化、去重和固定契约输出。
- Provider 级超时、重试、熔断、短期缓存和调用审计。

以下职责必须留在各 Agent：

- 从用户问题识别 Intent 和 Route。
- 从完整上下文生成最小化 SearchTask。
- 删除用户隐私和业务私有字段。
- 判断结果是否足以回答本领域问题。
- 决定使用本地模型、固定模板还是付费模型。

这样其他 Agent 可以复用搜索能力，但不能绕过自己的业务路由和安全策略。

### 6.10 部署拓扑

```text
本地开发 Agent
→ HTTPS /api/search
→ web-search-wrapper
→ Docker 内网 http://searxng:8080/search

生产环境 Agent
→ Docker 内网 http://web-search-wrapper:3002/api/search
→ Docker 内网 http://searxng:8080/search
```

目标状态下，公网域名应指向 `web-search-wrapper` 的受保护接口，不再把 SearXNG UI 和原始 API 作为多 Agent 的公共入口。

## 7. 最小代码改动清单

### 7.1 新增

```text
agent/routing/RequestRoute.java
agent/routing/ModelPolicy.java
agent/routing/RouteDecision.java
agent/routing/RouteExecutionPolicy.java
agent/routing/RouteExecutionPolicyRegistry.java
agent/routing/RequestRouter.java
agent/routing/RuleBasedRouteResolver.java
agent/routing/PaidModelGate.java
agent/routing/PaidModelPermit.java

llm/LocalAnswerClient.java

service/MarketFactResponder.java
service/ExplicitAnalysisExecutor.java

websearch/model/SearchPurpose.java
websearch/model/SearchTask.java
websearch/model/SearchResult.java
websearch/model/EvidenceBundle.java
websearch/gateway/WebSearchTask.java
websearch/gateway/WebSearchTaskMapper.java
websearch/planner/LocalSearchPlanner.java
websearch/policy/SearchPolicyValidator.java
websearch/gateway/WebSearchGateway.java
websearch/gateway/HttpWebSearchGateway.java
websearch/gateway/WebSearchProperties.java
websearch/gateway/WebSearchResponse.java
websearch/validation/EvidenceValidator.java
```

### 7.2 新增独立 web-search-wrapper

```text
web-search-wrapper/
├── package.json
├── Dockerfile
├── src/
│   ├── server.js
│   ├── app.js
│   ├── config.js
│   ├── auth.js
│   ├── contract.js
│   ├── policy.js
│   ├── cache.js
│   ├── provider/
│   │   ├── search-provider.js
│   │   └── searxng-search-provider.js
│   └── normalize/
│       └── search-result-normalizer.js
└── test/
    ├── app.test.js
    ├── contract.test.js
    ├── auth.test.js
    └── searxng-search-provider.test.js
```

Wrapper 使用独立 Node.js 容器运行，宿主机不需要额外安装 Node.js。它与现有 `stock-wrapper` 是两个职责不同、可独立扩缩容的服务：

```text
stock-wrapper      → 封装 stock-analysis-skill CLI
web-search-wrapper → 封装 SearXNG/未来搜索 Provider
```

### 7.3 修改

```text
IntentClassifier
→ 输出受限 RouteDecision，不再只返回四类 ChatIntent

AgentOrchestrator
→ 按 RequestRoute 显式分支
→ 删除所有请求统一进入 streamChatWithTools 的路径

KnowledgeExtractor
→ 改用 LocalAnswerClient，或只允许付费分析 Run 进入抽取

AgentRunService
→ 记录 ROUTE_DECISION、SEARCH_PLAN、SEARCH_CALL、EVIDENCE_VALIDATION、MODEL_GATE、MODEL_CALL

SessionState
→ 保存 route、modelPolicy、symbol、gateReason

application.yml / .env.example
→ 增加 Wrapper Base URL、Agent ID、Agent Token、超时和结果上限配置

deploy/docker-compose.yml
→ 增加 web-search-wrapper 与 SearXNG 内网服务和健康检查
```

### 7.4 保持不动

```text
stock-wrapper HTTP 契约
StockAnalysisGateway
StockSkillContractValidator 金融硬规则
PgVector 表结构
Redis 暂停恢复框架
现有前端 SSE 主连接
SearXNG 自身搜索排序实现
```

## 8. 审计事件

每次请求至少新增三类步骤：

```json
{
  "stepType": "ROUTE_DECISION",
  "intent": "STOCK_ANALYSIS",
  "route": "STOCK_DECISION",
  "modelPolicy": "PAID_AFTER_VALIDATED_SKILL",
  "allowedSkillCommands": ["stock"],
  "webSearchRequired": false,
  "reasonCode": "EXPLICIT_BUY_DECISION",
  "routeSource": "RULE"
}
```

```json
{
  "stepType": "MODEL_GATE",
  "allowed": true,
  "reasonCode": "VALIDATED_STOCK_OBSERVATION"
}
```

```json
{
  "stepType": "MODEL_CALL",
  "modelTier": "PAID",
  "provider": "deepseek",
  "purpose": "FINAL_INVESTMENT_ANALYSIS"
}
```

前端只展示结构化步骤，不展示隐藏思维链。

WebSearch 还需记录：

```json
{
  "stepType": "SEARCH_PLAN",
  "taskCount": 2,
  "purposes": ["NEWS_CATALYST", "COMPANY_ANNOUNCEMENT"],
  "containsPrivateData": false
}
```

```json
{
  "stepType": "SEARCH_CALL",
  "service": "web-search-wrapper",
  "provider": "searxng",
  "enginePolicy": "baidu,360search",
  "success": true,
  "resultCount": 7,
  "durationMs": 820
}
```

```json
{
  "stepType": "EVIDENCE_VALIDATION",
  "sufficient": true,
  "distinctDomains": 3,
  "authoritativeSourceCount": 1,
  "rejectionReason": null
}
```

审计默认只保存任务用途、规范化 URL、来源类型、数量、耗时和错误码，不保存用户隐私字段、Agent Token、完整网页正文或模型隐藏思维链。

## 9. 验收用例

| 输入 | Skill | WebSearch | 付费模型 | 预期 |
|---|---:|---:|---:|---|
| “你好” | 否 | 否 | 否 | 本地回答 |
| “什么是MACD” | 否 | 否 | 否 | RAG + 本地回答 |
| “最新印花税政策” | 否 | 是 | 否 | 固定 SearchTask + 本地模型总结 |
| “600519现在多少钱” | 是 | 否 | 否 | 返回 `data.quote` |
| “600519最近60天K线” | 是 | 否 | 否 | 返回 `data.history` |
| “600519能买吗” | 是 | 否 | 是 | Skill 校验后分析 |
| “我的持仓怎么调” | 是 | 否 | 是 | portfolio 校验后分析 |
| “600519为什么突然跌” | 是 | 是 | 是 | Skill 与外部证据均校验后放行 |
| “分析一下MACD” | 否 | 否 | 否 | 不因“分析”二字误付费 |
| “这个怎么样”且无当前标的 | 否 | 否 | 否 | 追问用户 |
| Skill 超时 | 失败 | 否 | 否 | 禁止付费，返回工具错误 |
| Skill 数据过期 | 是 | 否 | 否 | 禁止付费方向性分析 |
| WebSearch 超时 | 否 | 失败 | 否 | 明确搜索失败，不生成外部事实 |
| 涨跌原因但搜索证据不足 | 是 | 是 | 否 | 禁止付费，说明无法可靠归因 |
| 用户问题包含持仓和成本 | 否 | 是 | 否 | 搜索词必须删除私有字段 |
| 直接请求 `/search` 或缺少 Key | 否 | 失败 | 否 | 网关拒绝，不进入模型 |

测试必须通过 Mockito 验证非付费路由对 `DeepSeekClient` 的调用次数严格为零。

WebSearch 测试还必须验证：

- 原始用户问题不会发送给 Wrapper，也不会作为 SearXNG 的 `q` 参数发送。
- 每次最多三个 `SearchTask`、每个任务最多五条标准化结果。
- 股价、K 线和技术指标查询不会调用 `WebSearchGateway`。
- Agent Token 不出现在日志、审计事件、SSE 或异常消息中。
- 百度、360 单引擎失败时仍可返回另一个引擎的有效结果。
- 两个搜索源都失败时不调用付费模型。
- 未注册 Agent、错误 Token、超出配额和超出任务上限的请求必须由 Wrapper 拒绝。
- 不同 Agent 使用不同 Token，一个 Agent 的 Token 失效不能影响其他 Agent。
- StockWise 后端只解析 Wrapper 固定契约，不解析 SearXNG 原始 JSON。
- 每个 Route 只能执行映射表允许的 Skill Command。
- `MARKET_FACT` 即使兼容 Intent 为 `STOCK_ANALYSIS`，也不能进入付费模型。
- `EXTERNAL_RESEARCH` 即使兼容 Intent 为 `INVESTMENT_QA`，也不能加载 `stock-analysis-skill`。
- `QUANT_DECISION` 的 ETF 轮动只能调用 `quant`，板块排名只能调用 `sector`。
- `NEED_CLARIFICATION` 在任意初判 Intent 下对 Skill、WebSearch 和 DeepSeek 的调用次数都必须为零。

## 10. 建议实施顺序

1. 先增加路由枚举、`RouteExecutionPolicyRegistry`、规则路由器和映射测试，不改现有输出。
2. 增加 `LocalAnswerClient`，迁移普通闲聊和知识问答。
3. 增加 `MarketFactResponder`，迁移价格和日 K 查询。
4. 增加 `PaidModelGate`，收口所有 DeepSeek 调用。
5. 把深度分析改为 Java 先调 Skill、校验后再调用 DeepSeek。
6. 将知识抽取迁移到本地模型。
7. 定义跨 Agent 稳定的 `WebSearchTask`、传输层 `SearchResult` 和错误信封契约，并与 StockWise 领域对象隔离。
8. 新建独立 `web-search-wrapper`，完成 Agent 鉴权、SearXNG Provider、结果标准化、超时、熔断和测试。
9. 调整部署拓扑，使 SearXNG 只对 Wrapper 开放 Docker 内网接口。
10. 在 StockWise 增加 `LocalSearchPlanner`、搜索策略和 `HttpWebSearchGateway`。
11. 把 `EXTERNAL_RESEARCH` 迁移到 Wrapper + 本地模型。
12. 把 `MARKET_CAUSAL_ANALYSIS` 接入 Skill 与 WebSearch 双校验门禁。
13. 增加路由、搜索、证据、模型闸门和模型调用审计。
14. 完成 Wrapper 公网鉴权、逐 Agent 限流、SearXNG 原始接口封锁和跨 Agent 调用验收。

### 10.1 本轮实施结果（2026-07-28）

已完成：

- 新增 `RequestRoute`、`ModelPolicy`、`RouteDecision`、`RouteExecutionPolicyRegistry` 与确定性规则路由。
- 本地 Intent 仅作保守兜底；股票目标不明确时进入 `NEED_CLARIFICATION`，不再默认升级为付费分析。
- 新增 `ExplicitAnalysisExecutor`，由 Java 显式执行知识库、真实 Skill Command 和 WebSearch。
- 新增 `PaidModelGate`，深度分析必须通过 Route、Command、标的、契约、时效和外部证据检查。
- 原始 `DeepSeekClient` 已降为包内实现，业务层只能通过要求 `PaidModelPermit` 的 `PaidAnalysisClient` 调用。
- 价格、K 线和技术指标事实使用 `MarketFactResponder` 固定 JSON，不调用 DeepSeek。
- 普通问答、知识问答、外部搜索总结和知识抽取改用 `LocalAnswerClient`。
- 新增独立 `web-search-wrapper`，提供版本化协议、逐 Agent Token、固定响应、缓存、限流、超时和熔断。
- 公网搜索端点最终统一为 `https://bdlhxny.com/api/search`，协议版本由请求体 `schemaVersion` 管理，不在 URL 中重复增加 `v1`。
- 新增 `HttpWebSearchGateway`、`LocalSearchPlanner`、搜索策略与证据校验；搜索词不再发送完整会话、持仓成本等私有内容。
- Docker Compose 中 SearXNG 只向内部网络 `expose`，Java 后端只调用 Wrapper。
- Agent Run 新增 Route、模型门禁、模型等级审计，并在 `AgentRunContext` 中恢复工具预算硬限制。
- 旧版 `/api/stock-agent/chat` 已接入同一个 `PaidModelGate`，避免绕过主编排链直接付费推理。

自动化验证：

- Java：43个常规测试通过；另有1个默认关闭、通过环境开关执行的云端Wrapper真实集成测试，本次已显式开启并通过。
- Node.js Wrapper：8个测试全部通过，覆盖固定格式、鉴权、限流、部分失败、清洗去重和熔断。
- 已覆盖非付费 Route 对 `DeepSeekClient` 零调用、数据过期禁止付费、私有搜索字段清理、逐 Agent 限流和 SearXNG 熔断。
- 已生成独立云端部署包 `deploy/packages/web-search-wrapper-0.1.0-20260728.zip`，Dockerfile 可在解压目录直接构建。

部署验收结果：

- 云端 `web-search-wrapper` 已加入 `searxng_default` 网络，通过 `http://searxng:8080` 访问 SearXNG。
- Nginx `/api/search` 转发到 `127.0.0.1:3002/api/search`；2026-08-09 域名备案与 HTTPS 入口已完成，临时公网 `3002` 映射应按 `deploy/DOMAIN_DEPLOYMENT.md` 验收后撤销。
- 正确Token返回固定 `schemaVersion=1.0` 和标准化结果，错误Token返回401。
- 本地真实请求曾获得5条结果且无错误，Java `HttpWebSearchGateway` 云端集成测试有成功记录。
- SearXNG原始 `/search` 公网访问返回404。

仍待验收：

- 在真实 PostgreSQL、Redis、Ollama 环境验证正式 SSE 聊天入口。
- 根据前端事件消费情况验收 `route`、`modelTier`、`gateReason` 与行情固定 JSON 的展示。
- 域名备案与 HTTPS 入口已完成；待新 Nginx 路由验收后，关闭公网明文 `3001/3002/8000/8080/8081/8082/8083` 端口，并对数据库、Redis 和 Ollama 端口做同样收口。

## 11. 本草案建议的默认决策

- “为什么涨跌”属于付费综合分析，必须同时通过行情 Skill 与 WebSearch 证据校验。
- 当前价格、涨跌幅和日 K 使用现有 `stock` 命令，不新增虚构 Skill。
- 普通知识问答由 PgVector + 本地回答模型处理。
- 普通外部资料查询由共享 Wrapper + 本地模型处理，不调用 DeepSeek。
- `web-search-wrapper` 独立部署并允许多个 Agent 通过固定契约复用。
- 各 Agent 负责 Intent、Route、隐私清理和证据判断，Wrapper 不接入任何大模型。
- 每个 Agent 使用独立身份和 Token，不共享 StockWise 的调用凭证。
- SearXNG 默认使用百度和 360 搜索；Bing、搜狗在验证恢复前不进入默认引擎集合。
- 用户完整描述和持仓隐私不得发送给任何外部搜索引擎。
- 业务层永远只消费固定 `List<SearchResult>`，不得读取 Provider 原始 JSON。
- 搜索失败、证据不足或鉴权失败时禁止用付费模型补猜。
- 知识抽取改为本地模型，避免回答结束后产生隐藏付费调用。
- DeepSeek 不再自主决定是否调用工具，只负责消费已经校验的 Skill Observation 并生成最终深度分析。
