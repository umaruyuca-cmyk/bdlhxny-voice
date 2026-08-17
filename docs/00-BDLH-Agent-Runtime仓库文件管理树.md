# BDLH Agent Runtime 仓库文件管理树

> **文档状态：文件归属与落盘规则的唯一索引**
> **生效日期：2026-08-11**
> **用途：说明每个目录放什么、哪些文件仍然有效、新文件该落在哪里**
> **不是权威架构。** 与 [00-BDLH-Agent-Runtime统一生产架构.md](./architecture/00-BDLH-Agent-Runtime统一生产架构.md) 冲突时以架构文档为准；本文只管文件归属，不产生任何架构决策

## 0. 状态标记

本文沿用架构 §0.2 的标记，并补充两个文件级标记：

| 标记 | 含义 | 阅读方式 |
|---|---|---|
| `AUTHORITATIVE` | 当前有效且具备权威性 | 必读，冲突时以它为准 |
| `ACTIVE` | 当前有效的工作文档 | 需要时读 |
| `HISTORICAL` | 历史档案，只用于追溯 | 不要照它开发 |
| `RETIRED` | 遗留实现，按计划退出 | 不得新增依赖 |

判断一个文件是否还该被照着做，只看这一列，不看它的修改时间。

## 1. 顶层布局

| 路径 | 归属 | 状态 | 说明 |
|---|---|---|---|
| `README.md` | 入口 | `ACTIVE` | 定位、技术栈与文档导航；只做索引，不承载决策 |
| `docs/` | 文档 | — | 全部架构、Prompt、评审与本索引 |
| `bdlh-runtime-orchestrator/` | 代码 | `ACTIVE` | Python + LangGraph，Agent 编排唯一实现 |
| `bdlh-runtime-data/` | 代码 | `ACTIVE` | Java：认证与用户金融数据服务；不承载 Agent、LLM、记忆或外部工具调用 |
| `bdlh-runtime-console/` | 代码 | `ACTIVE` | 独立 Nginx 静态前端与契约测试 |
| `bdlh-web-search-adapter/` | 代码 | `ACTIVE` | 公开资料检索封装，经 Capability Gateway 调用 |
| `stock-wrapper/` | — | `RETIRED`（已移出仓库） | 旧 Node HTTP 包装层；勿恢复目录，勿配置 `STOCK_WRAPPER_*` |
| `skills/stock-analysis-skill/` | 代码 | `RETIRED` | 历史 CLI Skill，不承担生产编排或在线补数；非当前可插拔 Skill 宿主 |
| `db/` | 运维 | `ACTIVE` | schema 与迁移脚本 |
| `deploy/` | 运维 | `ACTIVE` | Compose、Nginx 与部署手册 |

## 2. `docs/`（重点）

```text
docs/
├── 00-BDLH-Agent-Runtime仓库文件管理树.md            本文，docs 根目录唯一文件
├── architecture/                   架构与 ADR
│   ├── 00-BDLH-Agent-Runtime统一生产架构.md          AUTHORITATIVE  生产架构唯一权威基线
│   ├── 00-BDLH-Agent-Runtime生产架构.drawio          AUTHORITATIVE  上文的唯一配套图
│   ├── 01-BDLH-Agent-Runtime定位与Skill扩展说明.md     ACTIVE         对外叙事与新人理解，非决策来源
│   ├── ADR-004-Suitability-v0规则阈值与校准.md            PROPOSED，未批准前生产规则失败关闭
│   ├── ADR-009-Runtime-Domain-Skill定位与命名.md          APPROVED
│   ├── ADR-010-SkillManifest与DomainDispatcher契约.md     APPROVED（§6.1 已落地）
│   ├── ADR-011-Memory分层与晋升边界.md                    APPROVED
│   ├── ADR-012-多Skill与多Agent演进门槛.md                APPROVED
│   ├── ADR-013-RAG作为可插拔KnowledgeSkill的边界.md        APPROVED（实施未排期）
│   ├── ADR-014-系统截断与用户截断Pause-Resume与会话入口路由.md  APPROVED（Pause/Turn Router 按切片落地）
│   └── ADR-015-Context组装服务与压缩策略.md               APPROVED（挂靠 ADR-011；禁止第二套 L 编号）
├── prompts/
│   └── 00-BDLH-Agent-Runtime生产开发实施Prompt.md    AUTHORITATIVE  唯一生产开发执行 Prompt
├── reviews/                        审查与阶段报告
│   ├── 00-BDLH-Agent-Runtime生产审查规范.md          AUTHORITATIVE  审查门禁与判定规则
│   ├── 01-BDLH-Agent-Runtime当前生产就绪审查报告.md  ACTIVE         最新一次全局审查快照
│   ├── 02-M2股票研究下沉-字段来源矩阵与实施报告.md  ACTIVE  阶段实施报告
│   ├── 04-Runtime定位升级修改意见.md        ACTIVE         定位升级依据与执行清单
│   └── 历史审查索引.md                      HISTORICAL     已清理报告的来源与去向
└── archive/                        历史档案（不指导开发，见该目录 README.md）
    ├── architecture/               5 个历史架构版本（V1→V3 演进档案）
    ├── diagrams/                   7 个旧 Java 链路时期图
    ├── proposals/                  3 个已否决或已实施的旧提案
    └── reviews/                    已被当前状态取代的阶段报告
```

三个子目录的分工是固定的：

| 子目录 | 只放 | 不放 |
|---|---|---|
| `architecture/` | 权威架构、ADR、配套图、历史架构档案 | 阶段实施报告、审查结论、开发指令 |
| `prompts/` | 给执行者的开发指令 | 架构决策；决策必须回落到架构文档或 ADR |
| `reviews/` | 审查规范、就绪报告、阶段报告、修改意见 | 权威结论；结论生效必须转为 ADR 或架构条款 |

`docs/` 根目录只保留本文一个文件。新增任何文档都必须落进上述三个子目录之一。

### 2.1 文件状态的辨别方法

`architecture/` 里的当前文档靠文件名前缀区分，不靠时间：

- `00-` / `01-` 前缀：当前文档，`00-` 是权威基线；
- `ADR-` 前缀：单点决策，看文件头 `状态` 字段，只有 `APPROVED` 才生效。

历史档案（5 个 `历史版本-*.md` 架构、7 个旧图、3 个旧提案）已统一移入 `docs/archive/`，不再与当前文档混放。它们的保留价值只有一条：追溯某个设计当初为什么被否。

同理，`reviews/` 里带编号的是当前阶段报告，`历史审查索引.md` 是已删除报告的存根。

## 3. 代码目录

### 3.1 `bdlh-runtime-orchestrator/`（Agent 编排唯一实现）

```text
bdlh-runtime-orchestrator/
├── pyproject.toml / uv.lock / Dockerfile / README.md
├── docs/langgraph-top-level-design.md      编排层顶层设计（模块级，非架构权威）
├── src/bdlh_runtime/
│   ├── api/            HTTP、身份、序列化、SSE
│   ├── runtime/        应用装配：配置、持久化工厂、预算、会话、历史、恢复、错误
│   ├── cognitive/      认知编排（内核，禁止 import 领域实现）
│   ├── domains/        领域边界：contracts.py（通用契约）、manifests.py（SkillManifest/DomainDescriptor 通用模型）、registry.py（Dispatcher）
│   │   └── finance/    第一个 Domain：runtime、planner、authorization、各 builder、manifests.py（finance descriptor + 3 SkillManifest）
│   ├── domain/         金融确定性计算引擎：指标、风险、回测、动量、策略、交易日历
│   ├── tools/          Capability Registry 与 Toolset 派生视图
│   ├── integrations/   供应商协议隔离（MCP、Java、Web）
│   ├── observations/   Observation 标准化：来源、质量、时间、降级
│   ├── guardrails/     四时点治理（内核）
│   ├── contracts/      跨层 Pydantic 契约
│   ├── memory/         Memory 抽象 + mem0 实现 + noop 降级
│   └── runtimes/       LangGraph 装配与旧 Root Graph（含 letta 空占位）
└── tests/              按上述模块镜像分目录，另有 tests/architecture（内核纯净度门禁 + manifest 启动校验门禁）
```

**四个必须记住的命名陷阱**，它们是当前目录混乱的主要来源：

| 目录 | 是什么 | 容易被误认为 |
|---|---|---|
| `domain/` | 金融确定性计算引擎（指标、风险、回测） | 领域边界 |
| `domains/` | 领域边界与 Domain Runtime（含 `finance/`） | 计算引擎 |
| `runtime/` | 应用装配与生产基础设施（配置、持久化、预算） | Agent Runtime 实现 |
| `runtimes/` | 具体编排框架装配（`langgraph/`、`letta/` 占位） | 应用装配 |

单复数是唯一区分。收敛方案见 §7，未执行前请按本表理解，不要凭直觉猜。

`runtimes/letta/` 只有 `.gitkeep`：生产禁止 Letta（架构 §1 决策 1），该目录不得填充实现。

### 3.2 `bdlh-runtime-data/`（Java）

| 包 | 状态 | 说明 |
|---|---|---|
| `api/`、`security/`、`config/`、`handler/`、`entity/`、`mapper/`、`dto/`、`service/` | `ACTIVE` | 认证、用户金融数据、只读查询与确认入口；Java 不承载 Agent、LLM、记忆或外部工具调用 |

Java 侧是用户事实的权威存储（L4），Agent 只能只读消费；用户资料的写入走独立认证 API，不是 Agent Capability。旧 Java Agent 链路已从仓库删除。

### 3.3 `bdlh-runtime-console/`

| 路径 | 状态 | 说明 |
|---|---|---|
| `public/` | `ACTIVE` | 实际发布的静态站点 |
| `test/` | `ACTIVE` | 前端契约测试 |
| `prototypes/` | `HISTORICAL` | 原型稿，不参与发布 |
| `legacy/` | `RETIRED` | 旧页面存档 |

## 4. 运维与支撑目录

| 路径 | 状态 | 说明 |
|---|---|---|
| `db/schema.sql`、`db/migrations/` | `ACTIVE` | PostgreSQL 主 schema 与按日期命名的迁移 |
| `db/mysql-schema.sql` | `HISTORICAL` | 早期 MySQL 阶段产物 |
| `deploy/docker-compose*.yml` | `ACTIVE` | 本地、云端与前端三套编排 |
| `deploy/nginx/bdlh-runtime.conf` | `ACTIVE` | 生产路由收口，`/api/v1/agent-runs*` 必须指向 Python |
| `deploy/DOMAIN_DEPLOYMENT.md` | `ACTIVE` | 域名、HTTPS 与端口收口手册 |
| `deploy/searxng/settings.yml` | `ACTIVE` | 检索后端配置，供 bdlh-web-search-adapter 使用 |
| `diagrams/*.drawio` | `HISTORICAL` | 旧链路图；`skill-result-display-flow` 另有两份重复 PNG 导出 |
| `proposals/*.md` | `HISTORICAL` | 三份旧方案（三层路由、付费模型路由、langchain4j 记忆优化） |

## 5. 新文件落盘规则

按「要写什么」直接查：

| 要写的东西 | 落盘位置 | 命名 | 必须同步登记 |
|---|---|---|---|
| 改变生产架构的决策 | `docs/architecture/` 新增 ADR | `ADR-0NN-主题.md` | 架构 §23.1 或 §23.2；文件头写状态 |
| 修订现有架构条款 | 直接改 `00-BDLH-Agent-Runtime统一生产架构.md` | — | §0.3 版本记录 |
| 给执行者的开发指令 | 改 `docs/prompts/00-...Prompt.md` | — | 该文 §25 修订记录 |
| 阶段实施报告 | `docs/reviews/` | `NN-M阶段-主题.md`，编号续排 | 无需，但结论若要生效必须转 ADR |
| 审查或改进意见 | `docs/reviews/` | `NN-主题.md` | 执行后在文件头标注执行状态 |
| 对外叙事、新人说明 | `docs/architecture/01-...` 或新建 `02-` | `0N-主题.md` | 架构 §22，并声明非权威 |
| 模块级设计说明 | 对应服务目录下的 `docs/` | 自由 | 不得与架构冲突 |
| 图 | 当前架构图只改 `docs/architecture/00-...drawio` | — | 不要在 `diagrams/` 新增当前图 |

四条硬规则：

1. **不要在 `docs/` 根目录新建文件**，除了本索引；
2. **不要新建第二份权威文档**。任何「我觉得该有个新的总架构」都应该改 `00-BDLH-Agent-Runtime统一生产架构.md` 或加 ADR；
3. **不要把评审结论当决策用**。`reviews/` 里的内容生效前必须转成 ADR 或架构条款；
4. **删除文档前先在索引里留存根**，参照 `reviews/历史审查索引.md` 的做法。

## 6. 命名约定

| 前缀 | 含义 |
|---|---|
| `00-` | 该目录的权威或主文件 |
| `01-` ~ `0N-` | 同目录的补充说明，按重要性排序 |
| `ADR-0NN-` | 单点架构决策，必须带状态字段 |
| `历史版本-0N-` | 已被取代的架构档案 |
| `NN-M{阶段}-` | 阶段相关报告，如 `02-M2股票研究下沉-...` |
| 日期前缀 `YYYYMMDD_` | 仅用于 `db/migrations/` |

## 7. 已知混乱点与处置状态

以下项目中，文档归档类已于 2026-08-11 执行完毕（历史版本、旧图、旧提案移入 `docs/archive/`，重复 PNG 删除，空目录清除）。剩余为代码改名项，仍排在 M3 收尾之后：

| 问题 | 现状影响 | 处置 | 状态 |
|---|---|---|---|
| `domain/` 与 `domains/`、`runtime/` 与 `runtimes/` 仅靠单复数区分 | 新人和 Agent 极易 import 错模块 | 重命名为 `finance_engine/`、`app/`、`orchestration/` 一类无歧义名 | 未执行（代码改名，排 M3 后） |
| `CapabilitySpec.analysis_types` 名不符实 | 字段实际表达 Skill 适用范围 | 改名为 `skill_scopes` | 未执行（04 号文档 P2 登记） |
| ~~`docs/migration/` 是空目录~~ | — | 已删除 | ✅ 已执行 |
| ~~`diagrams/` 与 `docs/architecture/` 都有架构图~~ | — | 旧图移入 `docs/archive/diagrams/` | ✅ 已执行 |
| ~~`skill-result-display-flow` 有两份 PNG~~ | — | 重复 PNG 已删除 | ✅ 已执行 |
| ~~`proposals/` 与 `docs/` 分离~~ | — | 移入 `docs/archive/proposals/` | ✅ 已执行 |
| ~~`历史版本-*.md` 与当前架构同目录~~ | — | 移入 `docs/archive/architecture/` | ✅ 已执行 |

优先级：剩余两项是纯代码改名，影响面大，需一次性完成并跑全量回归，排在 M3 收尾之后与 P2 批次一起做。

## 8. 维护规则

新增、删除或改变目录用途时，必须同步更新本文与 `README.md` 的文档索引；本文与实际文件不一致时，以 `git ls-files` 的实际结果为准并立即修正本文。
