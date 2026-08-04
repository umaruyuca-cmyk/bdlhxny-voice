# StockWise 首页、领域分析与 Skill 生态优化实施 Prompt

> 用途：将本文档完整复制给负责实施的 AI，让其根据现有 StockWise 项目完成前端信息架构、页面内容、Skill 接入说明和联调测试。  
> 重要边界：本 Prompt 要求实施代码，但不会改变现有业务路由、Agent 编排、ReAct、记忆、Skill 计算逻辑，除非本文明确要求。实施前必须先阅读项目根目录 `README.md`，并遵守其中的编码、测试、注释和提交规则。

## 一、项目背景

StockWise 当前由以下部分组成：

- `stockwise-backend`：Java/Spring Boot 后端，负责 Agent 编排、路由判断、ReAct、会话、SSE 输出、运行记录和 Skill 结果读取。
- `stock-wrapper`：Node.js/NPM 服务，负责调用股票、组合、量化、板块分析 Skill。
- `web-search-wrapper`：Node.js 搜索服务，负责结构化外部搜索。
- `stockwise-frontend`：独立部署的静态前端，当前首页已经改成深色科技感“研究基地”风格。
- `docs`：项目需求、架构、Skill 接入、部署和运维文档。

当前首页视觉方向是深色、蓝紫色、轻量科技感。不要改成绿色金融模板，不要堆叠过多动画，不要影响阅读和移动端使用。

## 二、当前必须解决的问题

### 1. 首页导航点击后没有内容

首页目前存在以下入口：

- `Skills` → `/docs/skill`
- `文档` → `/docs/agents`
- “领域分析” → `/agent`、`/docs/agents`
- “Skill 服务” → `/docs/skill`
- Skill 生态入口 → `/skill-dashboard.html`

但开发服务器和 Nginx 当前只处理首页、工作台、Agent、API 等路径，没有真正提供 `/docs/skill`、`/docs/agents`、`/docs/deployment` 页面。因此点击后会出现空白、404 或静态文件不存在。

必须补齐页面和路由，不能仅把链接改成不存在的文件。

### 2. “领域分析”的意义不清楚

“领域分析”不是另一个无法解释的 Agent 名称，也不是普通聊天的换皮。它表示：

> 针对某一类研究对象和专业问题，使用固定的路由、数据源、Skill、校验规则和输出模板，形成可重复的研究流程。

StockWise 当前的领域分析对象包括：

- 单只股票、ETF、基金等标的；
- 组合或持仓；
- 板块及行业热度；
- 量化指标、动量、波动率和历史回测；
- 新闻、舆情、讨论度和外部热度。

领域分析的基本链路为：

```text
用户问题
  → 识别研究对象和意图
  → 选择 Agent 路由
  → 判断是否需要外部搜索
  → 调用对应 Skill 获取结构化数据
  → 校验数据完整性、时间和来源
  → 由本地模型或付费分析模型进行解释
  → 输出结论、依据、风险和数据时间
```

必须在首页和领域分析文档中用普通用户能理解的语言说明：Agent 负责思考和编排，Skill 负责执行专业数据和计算，模型负责解释结果；三者不是三个重复的聊天机器人。

### 3. Skill 生态页面和接入规范不清晰

当前 `skill-dashboard.html` 使用了过时的统一接口 `/api/v1/analyze`，并直接显示内部 IP、固定版本和“云端运行中”等容易误导的信息。实际 `stock-wrapper` 接口是四个独立接口：

- `POST /api/v1/stock/analyze`
- `POST /api/v1/portfolio/analyze`
- `POST /api/v1/quant/analyze`
- `POST /api/v1/sector/analyze`

认证使用 `X-Internal-Token`，请求链路支持 `X-Request-ID`。公网页面严禁暴露真实 Token、内网地址或可以被滥用的管理信息。

### 4. 前端文档与当前后端契约可能不一致

当前后端已经以 `POST /api/v1/chat/stream` 为主要对话入口，并通过 SSE 返回 `status`、`agent_run`、`token`、`ask`、`clarification`、`quota`、`done`、`error` 等事件。

当前工作区已经删除游客分析次数限制相关的后端类和接口。除非项目重新实现完整的配额后端链路，否则前端和文档不得继续宣传或调用 `GET /api/v1/chat/guest-analysis-quota`。应以当前后端代码为准，清理旧页面中的配额 UI 和旧接口说明。

## 三、实施前必须执行的检查

实施 AI 必须先阅读并理解以下文件，不得直接凭经验重写页面：

1. `F:/privateskill/StockWise/README.md`
2. `F:/privateskill/StockWise/stockwise-frontend/API_INTEGRATION.md`
3. `F:/privateskill/StockWise/docs/16-个人网站与Agent服务规划.md`
4. `F:/privateskill/StockWise/docs/10-Skill对接文档.md`
5. `F:/privateskill/StockWise/stockwise-frontend/public/index.html`
6. `F:/privateskill/StockWise/stockwise-frontend/public/workspace.html`
7. `F:/privateskill/StockWise/stockwise-frontend/public/skill-dashboard.html`
8. `F:/privateskill/StockWise/stockwise-frontend/dev-server.js`
9. `F:/privateskill/StockWise/stockwise-frontend/nginx.conf`
10. 后端 `ChatController`、`AgentRunController`、`AgentOrchestrator` 以及当前测试。

实施时先确认当前工作区变更，不得使用 `git reset --hard`、`git checkout --` 或覆盖用户已有改动。保留当前 Agent、ReAct、SSE、Skill 结果和权限改造。

## 四、目标信息架构和页面路由

实现以下稳定的前端信息架构：

```text
/
├── 工作站
│   ├── /agent?name=general   通用研究
│   └── /agent?name=stock      标的研究
├── 文档
│   ├── /docs/skill            Skill 接入规范
│   ├── /docs/agents           Agent、Route、ReAct 说明
│   └── /docs/deployment       部署与联调说明
├── Skill 生态
│   └── /skill-dashboard.html  Skill 服务目录与接口浏览器
└── API 控制台
    └── /api-console.html      SSE、运行记录和 Skill 结果调试
```

要求：

- `/docs` 可以作为文档索引页，不得是空链接；
- `/docs/skill`、`/docs/agents`、`/docs/deployment` 必须是真实可访问页面；
- `dev-server.js` 和 `nginx.conf` 都要支持这些路径；
- 页面直接通过静态资源部署时也能打开，不能依赖不存在的后端文档服务；
- 支持浏览器刷新、深链接、移动端和中文字体；
- 现有 `/workspace`、`/agent/general`、`/agent/stock`、`/api-console.html` 不得失效。

## 五、首页内容改造要求

保留现有深色科技感视觉语言，但补齐可理解的产品说明。

首页首屏要让用户在 10 秒内明白三件事：

1. 这是一个研究型 Agent 工作站，不只是聊天窗口；
2. 用户可以直接提问，也可以选择标的进行结构化分析；
3. 复杂分析由 Skill 提供数据和计算，Agent 负责编排和解释。

“领域分析”卡片必须改成清晰描述，例如：

- 研究对象：股票、ETF、基金、组合、板块；
- 能力：行情、技术指标、动量、波动率、回测、板块热度、外部舆情；
- 结果：数据时间、证据来源、结论、风险、待确认项；
- 入口：进入标的研究或查看领域分析文档。

明确区分：

| 名称 | 作用 |
|---|---|
| 通用 Agent | 处理普通问答、资料整理、解释和不需要付费分析的请求 |
| Stock Agent | 识别股票/ETF/组合/板块等研究意图，编排数据和 Skill |
| stock-wrapper / Skill | 执行行情拉取、指标计算、回测和结构化分析，不负责自然语言闲聊 |
| Web Search Wrapper | 按固定查询结构获取外部新闻、舆情和讨论度证据 |
| 本地模型 | 处理普通问答、路由辅助、数据解释和低成本推理 |
| 付费分析模型 | 仅在满足正式分析条件且 Skill 数据完整时调用 |

## 六、领域分析页面要求

新增或完善 `/docs/agents`，用图文说明以下内容：

### 1. 什么情况下进入领域分析

- 用户明确要求分析、研判、比较、回测、仓位建议、板块热度或持仓风险；
- 用户提供了标的、组合、板块或明确研究对象；
- 问题需要实时行情、历史序列、指标或外部证据。

### 2. 什么情况下不进入付费分析

- 询问当前价格、单个字段、简单定义、普通知识；
- 只需要一次搜索结果或新闻摘要；
- Skill 数据不完整、过期或校验失败；
- 用户没有要求正式分析，且问题可以由本地模型直接回答。

### 3. 路由判断原则

```text
普通问答       → 通用 Agent + 本地模型
单值/行情查询  → Stock Agent 的轻量数据查询，不自动进入付费分析
实时 K 线      → Stock Agent + 对应行情数据接口
正式标的分析   → Stock Agent → stock Skill → 数据校验 → 付费分析模型
板块热度       → Stock Agent → sector Skill + Web Search → 热度证据汇总
新闻/舆情      → Web Search Wrapper → 本地模型整理
```

页面必须说明：调用 Skill 本身不等于调用付费大模型。Skill 是确定性的数据和计算层；只有在需要将结构化结果转成正式研判结论时，才根据 Route/Gate 结果调用付费模型。

## 七、Skill 接入文档 `/docs/skill`

将 Skill 接入规范重新整理成面向开发者的完整文档，至少包含以下章节：

### 1. 30 秒快速理解

说明调用方、Agent、stock-wrapper、Skill、数据源之间的关系，并给出一条最小调用链。

### 2. 实际服务和接口

只使用真实接口，不再展示不存在的统一 `/api/v1/analyze`：

| 能力 | 方法 | 路径 |
|---|---|---|
| 单标的分析 | POST | `/api/v1/stock/analyze` |
| 组合分析 | POST | `/api/v1/portfolio/analyze` |
| 量化分析 | POST | `/api/v1/quant/analyze` |
| 板块分析 | POST | `/api/v1/sector/analyze` |
| 存活检查 | GET | `/health` |
| 就绪检查 | GET | `/ready` |

### 3. 请求约定

说明：

- `Content-Type: application/json`；
- 服务间认证使用 `X-Internal-Token`；
- 调用链统一传递 `X-Request-ID`；
- Token 只能放在服务端环境变量或密钥管理系统；
- 浏览器不能直接持有内部 Token；
- 公共文档示例只能使用 `${STOCK_WRAPPER_URL}`、`${STOCK_WRAPPER_TOKEN}` 等占位符。

### 4. 请求和返回格式

根据 `docs/10-Skill对接文档.md` 和 `stock-wrapper` 当前实现，逐个接口给出：

- 请求字段、类型、是否必填、示例值；
- 成功响应 envelope；
- `data` 中的行情、K 线、指标、热度、证据和结论字段；
- 数据时间、来源、置信度、缺失字段和错误信息；
- 不同接口不可混用的字段。

不要杜撰后端没有实现的字段。如果某字段尚未稳定，明确标记为“当前版本不保证”。

### 5. 错误、超时和重试

必须说明 400、401/403、404、408/超时、429、5xx、上游数据缺失时的处理方式。重试必须有次数上限、退避时间和幂等请求 ID，禁止无限重试。

### 6. 调用示例

至少提供：

- curl 示例；
- Node.js 服务端示例；
- Java/Spring 服务端示例；
- Agent 调用时的最小 JSON 示例。

示例中不得出现真实公网 IP、真实 Token、数据库密码或内部管理地址。

### 7. 安全和部署

说明 Docker、端口、健康检查、Token 注入、日志脱敏和公网暴露边界。明确：Skill 服务可以独立部署，Agent 通过服务端调用；前端只访问 StockWise 后端，不直接访问带内部认证的 Skill。

### 8. 接入检查清单

提供可勾选清单：健康检查、认证、请求 ID、成功响应、数据缺失、超时、重试、日志脱敏、版本兼容和回滚。

## 八、Skill 生态页面 `/skill-dashboard.html`

页面不是静态“假运行状态”展示，而是一个清晰的 Skill 目录和接入入口。

必须完成：

- 显示 Skill 名称、用途、支持对象、接口列表、版本和文档入口；
- 将 `stock-wrapper` 的四个真实接口分开显示；
- 清楚标识“示例信息·非实时”或通过安全的后端能力接口动态获取；
- 删除真实 IP、真实 Token、内网地址和管理端口；
- 不在浏览器中实现 `X-Internal-Token` 调用；
- 提供“查看接入规范”按钮，跳转 `/docs/skill`；
- 提供“打开 API 控制台”按钮，跳转 `/api-console.html`；
- 对未接入的 Skill 显示“规划中”，不能显示为“运行中”；
- 页面在接口不可用时显示可理解的状态，不得出现空白或未捕获异常。

可以新增一个脱敏的后端接口 `GET /api/v1/public/capabilities`，返回公开能力目录，例如：

```json
{
  "agents": [
    {"id": "general", "name": "通用研究", "status": "available"},
    {"id": "stock", "name": "标的研究", "status": "available"}
  ],
  "skills": [
    {"id": "stock", "name": "单标的分析", "status": "available", "docsPath": "/docs/skill"},
    {"id": "portfolio", "name": "组合分析", "status": "available", "docsPath": "/docs/skill"},
    {"id": "quant", "name": "量化分析", "status": "available", "docsPath": "/docs/skill"},
    {"id": "sector", "name": "板块分析", "status": "available", "docsPath": "/docs/skill"}
  ]
}
```

该接口不得返回 Token、服务内部 URL、数据库信息、服务器 IP 或管理信息。若暂时不实现该接口，页面必须明确使用静态示例数据。

## 九、文档页面 `/docs`、`/docs/agents`、`/docs/deployment`

### `/docs`

作为文档索引页，展示三类文档：

- Agent 与路由：解释普通问答、领域分析、ReAct、Gate、记忆和 SSE；
- Skill 接入：解释四个 Skill 接口、认证、请求响应、错误和示例；
- 部署与联调：解释前端独立部署、后端部署、stock-wrapper、web-search-wrapper、Redis、PostgreSQL、Ollama 和环境配置。

### `/docs/deployment`

必须说明前后端分离：

- 修改前端只重新部署 `stockwise-frontend` 静态资源；
- 修改 Java 后端才重新构建和部署后端 JAR/容器；
- 修改 Skill wrapper 只部署对应 Node.js/Docker 服务；
- 前端不保存数据库密码、内部 Token 或付费模型密钥；
- `.env.cloud.example` 是模板，`.env.cloud` 是部署时实际配置，实际配置不得提交到 Git。

### 文档通用体验

- 所有文档使用统一的深色科技感主题；
- 提供左侧目录或顶部章节导航；
- 标题、表格、代码块、接口路径有足够对比度；
- 支持锚点跳转、复制代码、移动端折叠；
- 404 和空状态必须有明确说明和返回入口；
- 文档正文以中文为主，接口字段和代码保持英文。

## 十、API_INTEGRATION.md 必须同步

根据实际后端代码更新 `stockwise-frontend/API_INTEGRATION.md`：

- 以 `POST /api/v1/chat/stream` 为正式对话接口；
- 准确描述 SSE 事件：`status`、`agent_run`、`token`、`ask`、`clarification`、`quota`（仅在后端真实存在时）、`done`、`error`；
- 准确描述 `done` 中的 `runId`、`route`、`internalRoute`、`mode`、`modelTier`、`modelProvider`、`modelName`、`skillResultAvailable`、`skillResult` 等字段；
- 同步 Agent Run 查询接口和 Skill 结果接口；
- 清理已经删除的游客配额接口、旧的 `limit: 5` 示例和过时字段；
- 如果未来要恢复游客次数限制，必须同时实现后端身份识别、配额存储、校验、错误响应、前端展示和测试，不能只改文档或前端。

## 十一、后端改造边界

如实现 `GET /api/v1/public/capabilities`，只允许新增公开能力目录 Controller、DTO、Service 和测试，不得改动现有分析业务逻辑。

要求：

- 不返回任何密钥、内部 URL、服务器 IP、数据库连接信息；
- 只返回公开的 Agent/Skill 名称、状态、版本展示值和文档路径；
- 状态不能伪造为实时可用，无法探测时使用 `configured` 或 `unknown`；
- 失败时返回稳定 JSON，不影响聊天接口；
- 为正常响应、脱敏和异常场景增加测试。

## 十二、测试要求

实施完成后必须执行并记录：

### 前端

- 首页所有导航和卡片链接可打开；
- `/docs`、`/docs/skill`、`/docs/agents`、`/docs/deployment` 刷新不 404；
- Skill 页面不出现真实 Token、IP 或内部端口；
- 移动端布局正常；
- API 控制台可读取 SSE、运行记录和 Skill 结果；
- 旧页面中的失效配额调用已清理或有明确兼容处理。

### 后端

- `POST /api/v1/chat/stream` 正常输出 SSE；
- 普通问答不调用付费分析模型；
- 正式标的/板块分析按路由调用对应 Skill；
- Skill 结果缺失时不会生成“已验证”的虚假结论；
- Agent Run 查询和 Skill 结果查询权限不被破坏；
- 能力目录接口不泄露敏感配置。

### Skill wrapper

- `/health`、`/ready` 正常；
- 四个分析接口分别可调用；
- 缺 Token、错误 JSON、超时、上游无数据时返回稳定错误结构；
- `X-Request-ID` 能贯穿日志；
- 日志中不打印 Token。

## 十三、最终交付物

实施 AI 最终必须交付：

1. 首页入口和文案改造；
2. `/docs`、`/docs/skill`、`/docs/agents`、`/docs/deployment` 页面；
3. `skill-dashboard.html` 修正版；
4. `dev-server.js` 和 `nginx.conf` 的文档路由支持；
5. 更新后的 `API_INTEGRATION.md`；
6. 如确有必要，新增脱敏的 `/api/v1/public/capabilities` 及测试；
7. 前端契约测试、后端接口测试和联调结果；
8. 一份变更说明，列出修改文件、未实现项、已知限制和启动验证命令。

## 十四、实施纪律

- 先检查现状，再修改；
- 不要重写整个 Agent 核心；
- 不要把 Skill、WebSearch、付费模型混成一个黑箱；
- 不要在浏览器中暴露服务端密钥；
- 不要伪造“云端运行中”状态；
- 不要恢复当前后端已经删除的游客配额，除非同时得到完整产品需求并实现全链路；
- 不要删除现有注释、测试和用户未提交的改动；
- 所有新增中文内容必须使用 UTF-8；
- 代码完成后必须先运行测试，再报告结果；
- 若发现接口文档与代码冲突，以当前代码为准，并在变更说明中列出冲突。

## 十五、验收标准

只有同时满足以下条件才算完成：

1. 首页每个入口都有实际内容；
2. 用户能看懂“领域分析”是什么、什么时候使用、会得到什么结果；
3. Skill 生态页面展示真实接口和正确的接入路径；
4. 公共页面没有任何真实密钥、内部 IP 或管理信息；
5. 文档、前端、后端 SSE 契约一致；
6. 普通问答、行情查询、正式分析、板块热度和外部搜索的路由边界清晰；
7. 前后端可独立部署，文档明确说明部署边界；
8. 页面刷新、移动端、空状态、错误状态和接口异常都有可理解反馈；
9. 自动化测试和最小端到端联调通过；
10. 交付变更清单和已知限制。

完成后请用中文输出：修改文件列表、实现内容、测试命令及结果、仍需人工确认的事项。不要只说“已完成”，必须提供可验证证据。
