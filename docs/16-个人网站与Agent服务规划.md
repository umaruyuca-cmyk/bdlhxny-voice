# 个人智能研究网站：首页与模块规划

> 版本：v1.1 · 2026-08-01
>
> 本文只描述网站产品形态和模块边界。详细 Route、数据库、鉴权和部署规则继续维护在原有开发文档中。

## 1. 产品定位

这是一个个人智能研究工作站，不是传统的后台管理系统，也不是把所有技术能力堆在首页的 API 门户。

首页只回答三个问题：

1. 这是做什么的？
2. 我可以从哪里开始？
3. 除了对话，还提供哪些研究能力？

## 2. 首页结构

首页参考 Moonshot 的“品牌主张 + 主入口 + 能力展示 + 简洁导航”形式：

```text
顶部导航
├── 工作站
├── StockSkill
├── 文档
└── 关于

首屏
├── 一句产品主张
├── 简短说明
└── 开始研究 → 工作站

能力展示
├── 普通问答
├── Stock Agent
└── StockSkill API

底部
└── 项目简介、GitHub、文档、服务状态
```

首页不放完整聊天框、不展示复杂运行日志、不展示数据库/模型/部署信息。

建议首页文案：

> 把复杂的市场信息，整理成可以理解的研究结论。

副标题：

> 一个面向个人研究者的 AI 工作站，支持普通问答、标的分析和结构化 StockSkill 调用。

主按钮：`开始研究`

## 3. 网站模块

### 3.1 工作站

工作站是网站的核心使用区，包含两个 Agent：

| Agent | 作用 | 是否需要标的 |
|---|---|---:|
| 普通问答 Agent | 投资知识、研究方法、日常问答和资料整理 | 否 |
| Stock Agent | 标的、组合、量化和板块分析 | 个股决策需要 |

两个 Agent 使用独立 Session，但共用登录、运行记录和基础界面。Stock Agent 内部可以调用唯一真实 Skill：`stock-analysis-skill`。

### 3.2 StockSkill

StockSkill 是可独立调用的结构化分析服务，不是第三个 Agent。

它提供四类 Command：

- `stock`：单标的分析
- `portfolio`：组合分析
- `quant`：ETF 量化轮动
- `sector`：板块分析

首页只展示能力简介和“查看 API”入口，详细请求字段和响应契约放在文档页。

### 3.3 文档

文档模块保持简单，只保留三类内容：

1. `StockSkill 对接`：接口、鉴权、请求示例和错误码。
2. `Agent 工作逻辑`：普通问答 Agent、Stock Agent、Route 和 Skill 的关系。
3. `部署说明`：前端、Backend、StockSkill 和外网 HTTPS 部署方式。

文档页面建议使用 `/docs/skill`、`/docs/agents`、`/docs/deployment` 三个入口，不做复杂的知识库后台。

## 4. 外网服务边界

公网只暴露三个入口：

```text
HTTPS
├── /              个人网站首页
├── /workspace     双 Agent 工作站
└── /api/v1/...    聊天接口和受控 StockSkill API
```

以下服务只允许内网或回环访问：

- PostgreSQL / PgVector
- Redis
- Ollama
- SearXNG
- `stock-wrapper:3001`
- `web-search-wrapper:3002`

StockSkill 对外开放采用渐进方式：

1. 个人使用：单 Token，供自己的 Stock Agent 调用。
2. 受控开放：逐 Agent Token、限流、配额和审计。
3. 公开服务：注册、API Key 管理、用量统计和撤销机制。

当前仍按第一阶段实现，不把单一 `X-Internal-Token` 当作长期公网开放方案。

## 5. 开发顺序

### 第一阶段：首页

- 完成简洁首页视觉和响应式布局。
- 三个主要入口：工作站、StockSkill、文档。
- 保留二次元动态人物作为小型交互细节，不让人物遮挡主内容。

### 第二阶段：工作站

- 接入普通问答 Agent。
- 接入 Stock Agent 和标的选择。
- 展示 SSE 回答、运行状态和错误提示。

### 第三阶段：服务与文档

- 整理 StockSkill API 页面。
- 补充两个 Agent 的内部执行逻辑。
- 配置 HTTPS、Nginx 和外网服务入口。

## 6. 判断标准

- 用户打开首页后能快速理解产品并进入工作站。
- 首页不出现技术实现细节和长篇项目说明。
- 两个 Agent 的定位清楚，StockSkill 被理解为可调用能力，而不是第三个 Agent。
- 文档能让开发者调用 StockSkill，也能让维护者理解两个 Agent 的执行边界。
- 数据库、Redis、模型和内部 Wrapper 不暴露到公网。

