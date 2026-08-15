# BDLH Agent Runtime — 通用 Agent Runtime / 编排内核

> 认知编排 + 领域 Skill 插件 + 统一能力网关 + 四时点治理 + 确定性计算隔离。
> 金融（股票客观研究、用户适配性评估）是挂载其上的**第一个 Domain Skill**，不是内核本身。

## 项目定位

内核负责与业务领域无关的那部分：把「理解意图 → 选择行动 → 调度领域 → 受控调用外部能力 → 标准化观察 → 确定性计算 → 治理后表达」固定为可测试、可降级、可审计的链路。具体业务以 Skill 形式挂载，新增 Skill 或 Domain 只需注册，不改内核。

| 层 | 归属 | 说明 |
|---|---|---|
| API / Auth、认知编排、领域调度、能力网关、观察层、治理、持久化 | 内核 | 描述中不含金融词汇也成立，可迁移到非金融场景 |
| Domain Runtime（当前唯一实例：`finance`） | 领域 | Skill 宿主：校验、选 Skill、授权求交、组装结果 |
| Skill（stock-research / portfolio-health / suitability-evaluation） | 领域 | 单一业务能力实现，配合确定性引擎产出结构化结果 |

定位说明见 [01-BDLH-Agent-Runtime定位与Skill扩展说明.md](docs/architecture/01-BDLH-Agent-Runtime定位与Skill扩展说明.md)，权威架构见 [00-BDLH-Agent-Runtime统一生产架构.md](docs/architecture/00-BDLH-Agent-Runtime统一生产架构.md)。

**当前实施状态：迁移进行中。** 默认对外路径仍是旧编排链路；领域运行时与结构化研究输出已完成开发但受发布门禁约束。准确状态见架构文档 §3 与 §20，不要把本文当作已全部落地的证明。

## 技术栈

- **Agent 编排（唯一）**: Python 3.11+ + FastAPI + LangGraph（`bdlh-runtime-orchestrator`，端口 8090）
- **用户与认证数据服务**: Java 17 + Spring Boot（`bdlh-runtime-data`，端口 8081）；对 Agent 只暴露只读数据接口
- **前端**: 独立 Nginx 静态站点（`bdlh-runtime-console`）
- **外部数据**: cn-financial / akshare-one MCP + Web Search Wrapper（`bdlh-web-search-adapter`）
- **数据库**: PostgreSQL 16（Checkpoint / 会话 / 运行索引 / 历史 / 审计）+ Redis 7（缓存与限流，非真源）
- **模型**: DeepSeek；确定性金融计算不依赖模型
- **可选记忆**: Mem0（L3 语义记忆，失败降级为无记忆）
- **部署**: Docker Compose + Nginx

历史 Java Agent 链路与 Node `stock-wrapper` 属于退出中的遗留路径（架构文档标记 `RETIRED`），新功能不得依赖。

## 文档索引

### 当前权威文档

| 文档 | 说明 |
|------|------|
| [00-BDLH-Agent-Runtime仓库文件管理树.md](docs/00-BDLH-Agent-Runtime仓库文件管理树.md) | 每个目录放什么、哪些文件仍有效、新文件落在哪里 |
| [00-BDLH-Agent-Runtime统一生产架构.md](docs/architecture/00-BDLH-Agent-Runtime统一生产架构.md) | 生产架构唯一权威基线 |
| [00-BDLH-Agent-Runtime生产架构.drawio](docs/architecture/00-BDLH-Agent-Runtime生产架构.drawio) | 配套架构图 |
| [01-BDLH-Agent-Runtime定位与Skill扩展说明.md](docs/architecture/01-BDLH-Agent-Runtime定位与Skill扩展说明.md) | 定位与扩展面说明（非决策来源） |
| [00-BDLH-Agent-Runtime生产开发实施Prompt.md](docs/prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md) | 唯一生产开发执行 Prompt |
| [00-BDLH-Agent-Runtime生产审查规范.md](docs/reviews/00-BDLH-Agent-Runtime生产审查规范.md) | 审查门禁与判定规则 |
| [01-BDLH-Agent-Runtime当前生产就绪审查报告.md](docs/reviews/01-BDLH-Agent-Runtime当前生产就绪审查报告.md) | 最新一次全局审查快照 |

### 架构决策记录（ADR）

| ADR | 主题 | 状态 |
|---|---|---|
| [ADR-004](docs/architecture/ADR-004-Suitability-v0规则阈值与校准.md) | Suitability v0 规则阈值与校准 | `PROPOSED`，未批准前不得进生产规则 |
| [ADR-009](docs/architecture/ADR-009-Runtime-Domain-Skill定位与命名.md) | Runtime / Domain / Skill 三层定位与命名 | `APPROVED` |
| [ADR-010](docs/architecture/ADR-010-SkillManifest与DomainDispatcher契约.md) | Skill Manifest 与 Domain Dispatcher 契约 | `APPROVED`（descriptor/manifest 切片已落地） |
| [ADR-011](docs/architecture/ADR-011-Memory分层与晋升边界.md) | Memory 五层分层与晋升边界 | `APPROVED` |
| [ADR-012](docs/architecture/ADR-012-多Skill与多Agent演进门槛.md) | 多 Skill 与多 Agent 演进门槛 | `APPROVED` |
| [ADR-013](docs/architecture/ADR-013-RAG作为可插拔KnowledgeSkill的边界.md) | RAG 作为可插拔 Knowledge Skill 的边界 | `APPROVED`（实施未排期） |
| [ADR-014](docs/architecture/ADR-014-系统截断与用户截断Pause-Resume与会话入口路由.md) | 系统/用户截断 Pause·Resume 与 Turn Router | `APPROVED` |
| [ADR-015](docs/architecture/ADR-015-Context组装服务与压缩策略.md) | Context 组装与压缩（挂靠 ADR-011） | `APPROVED` |

### 设计、评审与运维

| 文档 | 说明 |
|------|------|
| [04-Runtime定位升级修改意见.md](docs/reviews/04-Runtime定位升级修改意见.md) | 定位升级的依据与执行清单 |
| [02-M2股票研究下沉-字段来源矩阵与实施报告.md](docs/reviews/02-M2股票研究下沉-字段来源矩阵与实施报告.md) | M2 字段来源矩阵 |
| [03-M3前置数据契约差距与实施状态.md](docs/archive/reviews/03-M3前置数据契约差距与实施状态.md) | M3 前置数据契约历史报告 |
| [历史审查索引.md](docs/reviews/历史审查索引.md) | 已清理审查报告的来源与去向 |
| [langgraph-top-level-design.md](bdlh-runtime-orchestrator/docs/langgraph-top-level-design.md) | Python 编排层顶层设计 |
| [DOMAIN_DEPLOYMENT.md](deploy/DOMAIN_DEPLOYMENT.md) | HTTPS 路由、MCP 子域名与公网端口收口手册 |
| [schema.sql](db/schema.sql) | 数据库建表语句 |
| [docker-compose.yml](deploy/docker-compose.yml) | 容器化部署配置 |

`docs/archive/` 下是版本演进档案、旧 Java 链路时期图与旧提案，只用于追溯，不指导开发。当前唯一配套架构图是 `docs/architecture/00-BDLH-Agent-Runtime生产架构.drawio`。

## 快速开始

```powershell
# Python 编排服务（Agent 唯一编排入口）：运行全量回归
Set-Location bdlh-runtime-orchestrator
uv run pytest -q

# Java 用户与认证数据服务：本地默认加载 application-dev.yml
Set-Location bdlh-runtime-data
mvn spring-boot:run
curl http://localhost:8080/actuator/health
start http://localhost:8080/docs
```

生产端口与路由归属（Nginx 收口、Python 8090、Java 8081）见架构文档 §4.1 与 §17；本地端口可能与生产不同，以各服务配置为准。

## Agent Run 回放

对话流会返回 `agent_run` 事件及稳定的 `runId`。运行审计记录由 Python 编排服务提供（生产经 Nginx 收口，架构文档 §4.1 要求 `/api/v1/agent-runs*` 路由到 Python）：

```bash
curl "http://localhost:8090/api/v1/agent-runs?limit=20"
curl "http://localhost:8090/api/v1/agent-runs/{runId}"
```

回放只保存工具 Action、Observation、策略拒绝、错误摘要和最终回答，不保存模型隐藏思维链。`run_id` 与 `thread_id` 语义不同，不得混用。

## 项目结构

```
BDLH Agent Runtime/
├── README.md
├── docs/
│   ├── architecture/            # 权威架构、ADR、配套架构图
│   ├── prompts/                 # 唯一生产开发执行 Prompt
│   ├── reviews/                 # 审查规范、就绪报告、阶段实施报告与修改意见
│   └── archive/                 # 历史档案（旧架构版本、旧图、旧提案，不指导开发）
├── bdlh-runtime-orchestrator/          # Python + LangGraph：Agent 编排唯一实现
│   ├── src/bdlh_runtime/  # api / cognitive / domains / tools / observations / guardrails / domain
│   └── tests/                   # 含 tests/architecture 内核纯净度门禁
├── bdlh-runtime-data/           # Java：认证与用户金融数据服务（对 Agent 只读）
├── bdlh-runtime-console/          # 独立 Nginx 静态前端与前端契约测试
├── bdlh-web-search-adapter/          # 公开资料检索封装
├── db/                          # schema 与迁移脚本
├── deploy/                      # Docker Compose、Nginx 与部署手册
├── skills/                      # 历史 CLI Skill（RETIRED）
└── stock-wrapper/               # 历史 Node HTTP 包装层（RETIRED）
```

`skills/stock-analysis-skill/` 与 `stock-wrapper/` 是遗留路径，Python 新链路禁止依赖，按架构文档计划退出。

## 分支管理

单人开发采用 `main` + `dev` 两分支：

| 分支 | 用途 |
| --- | --- |
| `main` | 默认开发与发布分支，当前工作区默认使用 |
| `dev` | 预发布验证分支，需要隔离联调时可切出使用 |

日常直接在 `main` 上开发提交；`dev` 仅在需要隔离验证时使用。不再使用多 worktree 多分支并行模式。

```powershell
git status                 # 查看当前改动
git add . && git commit    # 提交
git push origin main       # 推送
```
