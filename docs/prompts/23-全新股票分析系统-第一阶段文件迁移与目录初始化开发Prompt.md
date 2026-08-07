# StockWise 全新股票分析系统
# 第一阶段：文件迁移与目录初始化开发 Prompt

> 版本：v1.0
>
> 阶段范围：只做文件迁移、文档归档和新目录创建。
>
> 严禁事项：本阶段不编写 Python 业务代码，不实现 LangGraph，不实现 Agent、Tool、MCP、Skill、Domain Service，不改数据库结构，不改前端逻辑，不修改 Java 后端。

---

## 1. 你的角色

你是 StockWise 项目的文件整理和工程初始化执行 AI。

当前任务不是开发功能，而是为全新 Python 股票分析系统建立干净的目录骨架，并将已经形成的架构设计文档、复核文档和开发 Prompt 归档到统一位置。

本阶段所有操作必须可回滚、可审计、可复核。

---

## 2. 当前架构决策

### 2.1 新系统定位

新系统是：

```text
全新 Python 分析后端
+ 现有前端页面和视觉素材复用
+ 全新数据库结构
+ 全新 LangGraph / LangChain 架构
```

新系统只做：

- 股票和市场研究；
- 个股、ETF、基金和板块分析；
- 持仓和组合分析；
- 模拟调仓建议；
- 策略设计；
- 回测；
- 知识和记忆沉淀。

新系统不做：

- 真实下单；
- 撤单、改单和券商回执；
- Broker MCP；
- 交易执行 Worker；
- 订单状态机；
- 旧 Java Agent 编排；
- 旧 Java Skill 门禁体系。

### 2.2 旧系统处置

旧 Java 后端不进入新系统目录，也不作为新系统运行依赖。

以下目录不迁移到新 Python 系统：

```text
stockwise-backend/
stock-wrapper/
web-search-wrapper/
skills/stock-analysis-skill/
```

说明：

- `stockwise-backend/`：旧 Java 后端，不迁移、不改造、不接入新 Runtime；
- `stock-wrapper/`：旧 Node 业务包装，不纳入新目标目录；
- `web-search-wrapper/`：旧搜索包装，不纳入新目标目录；
- `skills/stock-analysis-skill/`：旧 Skill 仅作为未来算法参考或对比来源，不作为新系统当前依赖。

本阶段不删除上述旧目录。它们不进入新系统结构，也不允许被新目录引用。后续是否清理由单独的清理任务决定。

### 2.3 前端处置

现有 `stockwise-frontend/` 是唯一保留并复用的旧系统资产。

本阶段只做：

- 保留前端页面、CSS、图片和静态资源；
- 归档前端文档和原型的位置；
- 为后续 Python API 接入预留目录。

本阶段不做：

- 修改 HTML 业务逻辑；
- 修改 `workspace-common.js`；
- 修改 SSE 解析；
- 修改 API 地址；
- 引入 React、Vue 或构建链；
- 删除旧页面。

后续前端接入阶段再单独修改 API 和 SSE 消费逻辑。

---

## 3. 强制执行边界

### 3.1 本阶段允许的操作

只允许：

1. 创建新目录；
2. 创建必要的文档归档目录；
3. 复制架构文档、复核文档和 Prompt 到目标文档目录；
4. 迁移或复制明确列出的文档文件；
5. 输出目录树和迁移清单；
6. 做只读校验、文件哈希校验和 Git 状态检查。

### 3.2 本阶段禁止的操作

禁止：

- 创建 `.py` 业务实现文件；
- 创建 LangGraph 代码；
- 创建 LangChain Agent；
- 创建 Tool 实现；
- 创建 MCP Server 或 MCP Client 实现；
- 创建 Skill 实现；
- 创建 Domain Service 实现；
- 修改 Java、Node、HTML、CSS、JS、SQL、YAML、Dockerfile；
- 修改 `pom.xml`、`package.json` 或 `pyproject.toml`；
- 安装依赖；
- 启动服务；
- 修改数据库；
- 修改 Redis；
- 执行数据库迁移；
- 删除旧目录或旧文件；
- 使用 `git reset`、`git checkout --`、`git clean` 等破坏性命令；
- 覆盖已有文件而不先做哈希和内容确认。

### 3.3 迁移安全规则

本阶段对外部 `F:` 盘文档默认采用：

```text
读取源文件
→ 创建目标目录
→ 复制文件
→ 校验源文件和目标文件 SHA-256
→ 保留源文件
```

除非用户明确要求，否则不删除 `F:` 盘原件，不执行跨盘 Move-Item 删除源文件的行为。

---

## 4. 工作区和源文件

工作区：

```text
D:\bdlh-agent\bdlhxny-agent
```

当前主要源文件：

```text
F:\qq\21-全新股票分析系统-Agent需求与开发设计.md
F:\qq\21-全新股票分析系统-设计复核意见.md
F:\qq\21-全新股票分析系统-融合架构设计.md
D:\bdlh-agent\bdlhxny-agent\docs\22-全新股票分析系统-架构复核意见.md
D:\bdlh-agent\bdlhxny-agent\docs\08-开发指挥Prompt.md
```

注意：

- `docs/08-开发指挥Prompt.md` 是旧 Java 系统开发 Prompt；
- 不删除、不覆盖、不修改旧 Prompt；
- 本 Prompt 只服务于新系统第一阶段目录初始化；
- 任何旧 Prompt 中的 Java、Spring AI、付费模型门禁、旧 Skill、旧 Route 规则，均不适用于本阶段。

---

## 5. 目标目录

### 5.1 新 Python 系统目标目录

只创建目录，不创建 Python 实现文件：

```text
stockwise-analysis/
├── src/
│   └── stockwise_analysis/
│       ├── api/
│       │   ├── native/
│       │   └── compat/
│       ├── application/
│       │   ├── graphs/
│       │   │   └── subgraphs/
│       │   ├── nodes/
│       │   └── agents/
│       ├── domain/
│       │   ├── market/
│       │   ├── portfolio/
│       │   ├── risk/
│       │   ├── strategy/
│       │   └── backtest/
│       ├── tools/
│       ├── observations/
│       ├── contracts/
│       ├── integrations/
│       │   ├── market_data/
│       │   ├── research_data/
│       │   └── mcp/
│       ├── persistence/
│       │   ├── database/
│       │   ├── redis/
│       │   └── checkpointer/
│       ├── workers/
│       └── observability/
├── tests/
│   ├── graphs/
│   ├── agents/
│   ├── tools/
│   ├── domain/
│   └── integration/
└── docs/
```

不要创建以下目录：

```text
stockwise-analysis/skills/
stockwise-analysis/orders/
stockwise-analysis/broker/
stockwise-analysis/trading/
```

Skill 后续重新设计，交易相关模块不属于本系统范围。

### 5.2 文档目录

在现有 `docs/` 下创建：

```text
docs/
├── architecture/
├── reviews/
├── prompts/
└── migration/
```

不移动、不删除现有 `docs/` 文件。新目录只用于本次新系统文档归档。

### 5.3 数据库和部署目录

只创建目录：

```text
db/
└── migrations/

deploy/
├── analysis/
└── frontend/
```

本阶段不创建 SQL、Docker Compose 或 Dockerfile 内容。

---

## 6. 文档迁移清单

默认采用“复制并校验，保留源文件”的方式。

### 6.1 架构文档

| 源文件 | 目标文件 |
|---|---|
| `F:\qq\21-全新股票分析系统-Agent需求与开发设计.md` | `docs/architecture/21-全新股票分析系统-Agent需求与开发设计.md` |
| `F:\qq\21-全新股票分析系统-融合架构设计.md` | `docs/architecture/21-全新股票分析系统-融合架构设计.md` |

### 6.2 复核文档

| 源文件 | 目标文件 |
|---|---|
| `F:\qq\21-全新股票分析系统-设计复核意见.md` | `docs/reviews/21-全新股票分析系统-设计复核意见.md` |
| `D:\bdlh-agent\bdlhxny-agent\docs\22-全新股票分析系统-架构复核意见.md` | `docs/reviews/22-全新股票分析系统-架构复核意见.md` |

### 6.3 当前 Prompt

当前 Prompt 保存为：

```text
docs/prompts/23-全新股票分析系统-第一阶段文件迁移与目录初始化开发Prompt.md
```

不要覆盖旧的：

```text
docs/08-开发指挥Prompt.md
```

### 6.4 文档引用处理

只允许修正迁移后文档中的相对路径引用，不修改设计内容。

允许修改：

- `./21-...` 这类文档相对路径；
- 指向旧文档位置的链接，使其指向 `docs/architecture/` 或 `docs/reviews/`。

禁止修改：

- Graph 设计；
- Agent 模式；
- Tool、MCP、Skill 设计；
- 状态结构；
- API 契约；
- 数据库设计；
- 开发阶段定义。

如果路径修正会导致内容大范围变化，先记录为待处理项，不要自行扩展任务。

---

## 7. 现有前端文件处置

### 7.1 保留范围

现有以下目录作为后续前端复用基础：

```text
stockwise-frontend/public/
stockwise-frontend/public/assets/
stockwise-frontend/public/docs/
stockwise-frontend/prototypes/
stockwise-frontend/test/
```

### 7.2 本阶段不迁移前端业务文件

不要把 HTML、JS、CSS 复制到 Python 后端目录。

不要把前端页面移动到 `stockwise-analysis/`。

前后端保持两个独立目录：

```text
stockwise-frontend/
stockwise-analysis/
```

### 7.3 只做目录预留

如果现有前端没有以下目录，可以创建：

```text
stockwise-frontend/public/analysis/
stockwise-frontend/public/analysis/assets/
stockwise-frontend/docs/api/
```

本阶段不要创建新页面，不修改现有页面。

---

## 8. 执行步骤

严格按以下顺序执行：

### Step 1：只读检查

输出：

- 当前工作区绝对路径；
- 当前 Git 分支；
- 当前 Git 状态；
- 源文档是否存在；
- 目标目录是否已经存在；
- 目标文件是否已经存在；
- 现有前端目录树摘要。

如果发现目标文件已经存在且内容不同，停止该文件迁移并报告，不覆盖。

### Step 2：创建目录

创建第 5 节所列的空目录。

不要创建 Python、SQL、YAML、Docker、JavaScript 或其他实现文件。

### Step 3：复制文档

按照第 6 节清单复制文档。

复制前记录：

```text
source path
source size
source SHA-256
```

复制后记录：

```text
target path
target size
target SHA-256
```

源文件和目标文件 SHA-256 不一致时，立即停止并报告。

### Step 4：处理相对路径

只修复因为文档归档产生的相对路径错误。

每一个改动必须记录：

```text
文件
原路径
新路径
修改原因
```

如果不需要修改路径，不要改文档内容。

### Step 5：最终校验

执行：

- 目标目录存在性检查；
- 文档文件哈希检查；
- 迁移文件数量检查；
- 新目录中不存在 `.py`、`.java`、`.js`、`.ts`、`.sql`、`.yaml`、`.yml`、`Dockerfile` 等实现文件；
- Git diff 检查；
- Git status 检查。

---

## 9. Git 和安全规则

本阶段不自动提交 Git。

执行结束后只报告：

```text
git status --short
git diff --stat
```

禁止：

- 自动 commit；
- 自动 push；
- 自动删除旧系统；
- 自动清理未跟踪文件；
- 自动格式化整个项目；
- 触碰与本任务无关的用户修改。

如果工作区有用户已有修改，保留这些修改，不覆盖、不重置。

---

## 10. 验收标准

只有全部满足以下条件，才算本阶段完成：

1. `stockwise-analysis/` 的新目录骨架已创建；
2. `docs/architecture/`、`docs/reviews/`、`docs/prompts/`、`docs/migration/` 已创建；
3. 指定设计和复核文档已经复制并通过 SHA-256 校验；
4. 源文档仍然存在，没有被删除；
5. 没有创建任何业务实现代码；
6. 没有修改 Java、Node、前端、SQL、Docker 或配置文件；
7. 没有修改数据库和 Redis；
8. 没有启动服务和安装依赖；
9. `git diff` 中只包含本阶段允许的文档路径变化；
10. 输出完整迁移清单、目录树、校验结果和未处理事项。

---

## 11. 最终报告格式

```text
## 执行结果

状态：完成 / 部分完成 / 阻塞

## 新建目录
- ...

## 已复制文件
| 源文件 | 目标文件 | 源 SHA-256 | 目标 SHA-256 | 状态 |
|---|---|---|---|---|

## 路径修正
- 无 / 列出每一项

## 未执行事项
- Python 代码：未执行
- LangGraph：未执行
- Tool：未执行
- MCP：未执行
- Skill：未执行
- 数据库：未执行
- 前端逻辑：未执行

## Git 状态
```text
粘贴 git status --short
```

## Git Diff 摘要
```text
粘贴 git diff --stat
```

## 风险和待确认事项
- ...
```

---

## 12. 本阶段一句话指令

```text
只创建新目录并归档指定设计文档；不写任何业务代码，不改任何旧后端、前端、数据库或部署配置，不删除原文件，不执行依赖安装和服务启动。
```
