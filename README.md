# StockWise — 智能投资分析 Agent

> 基于现有 stock-analysis-skill CLI 工具升级的垂直领域 AI Agent

## 项目定位

将一次性命令行分析工具，升级为具备**多轮对话**、**知识增强**、**主动服务**的智能投资分析助手。

| 维度 | 原 CLI 工具 | StockWise Agent |
|------|-----------|-----------------|
| 交互 | 一次性命令 | 多轮自然语言对话 |
| 状态 | 无状态 | 三层记忆（短期/中期/长期） |
| 知识 | 纯指标计算 | RAG 知识库（术语/策略/政策） |
| 主动 | 被动触发 | 定时推送 + 价格预警 |
| 界面 | 终端 | Web 聊天 + 看板 |

## 技术栈

- **Agent 引擎**: Java 17 + Spring Boot 3.4 + Spring AI
- **分析工具**: 独立 Node.js `stock-wrapper` 通过 HTTP 封装 `stock-analysis-skill`，与 Java Agent 分镜像部署
- **数据库**: PostgreSQL 16 + PgVector + Redis 7
- **模型**: DeepSeek 深度推理 + Ollama 轻量分类与 Embedding
- **部署**: Docker Compose（Java 后端镜像 + Node Wrapper/Skill 镜像）

## 文档索引

| 文档 | 说明 |
|------|------|
| [00-需求规格说明书-v3.md](docs/00-需求规格说明书-v3.md) | 当前需求唯一真源 |
| [08-开发指挥Prompt.md](docs/08-开发指挥Prompt.md) | 当前开发指挥 Prompt 与实施路线 |
| [后端架构分析.md](docs/后端架构分析.md) | 后端现状架构分析 |
| [StockWise系统总架构.drawio](diagrams/StockWise系统总架构.drawio) | 系统部署与组件总览图 |
| [后端现状架构图.drawio](diagrams/后端现状架构图.drawio) | 后端现状架构图 |
| [ReAct-Skill-记忆优化方案.md](docs/ReAct-Skill-记忆优化方案.md) | ReAct、Skill、记忆与向量检索优化方案 |
| [09-核心分析依据.md](docs/09-核心分析依据.md) | 对外核心分析依据、证据等级、Rule ID与能力边界 |
| [10-Skill对接文档.md](docs/10-Skill对接文档.md) | 其他Agent调用云端Skill的接口、鉴权与消费规则 |
| [11-Skill-Docker部署文档.md](docs/11-Skill-Docker部署文档.md) | 运维Agent使用的Docker、Nginx、验证与回滚手册 |
| [12-后端云端部署与联调.md](docs/12-后端云端部署与联调.md) | Java Backend连接云端PG、Redis、Ollama与Wrapper的部署联调手册 |
| [13-前端独立部署.md](docs/13-前端独立部署.md) | 独立Nginx前端的构建、代理、测试与发布手册 |
| [15-云端配置运维.md](docs/15-云端配置运维.md) | application-dev.yml与application-prod.yml使用说明 |
| [16-个人网站与Agent服务规划.md](docs/16-个人网站与Agent服务规划.md) | 个人网站首页、双 Agent、StockSkill 外网服务与文档中心总规划 |
| [Agent与记忆目标架构.drawio](diagrams/Agent与记忆目标架构.drawio) | Agent 与记忆系统目标架构图 |
| [整体调用逻辑.drawio](diagrams/整体调用逻辑.drawio) | 当前请求入口、路由、Skill、搜索、记忆与模型调用逻辑 |
| [schema.sql](db/schema.sql) | 数据库建表语句 |
| [docker-compose.yml](deploy/docker-compose.yml) | 容器化部署配置 |
| [DOMAIN_DEPLOYMENT.md](deploy/DOMAIN_DEPLOYMENT.md) | `bdlhxny.com` HTTPS 路由、MCP 子域名和公网端口收口手册 |

## 快速开始

```bash
# 1. 本地默认加载application-dev.yml
Set-Location stockwise-backend
mvn spring-boot:run

# 2. 验证
curl http://localhost:8080/actuator/health

# 3. 打开美化后的API文档
start http://localhost:8080/docs
```

## Agent Run 回放

对话流会返回 `agent_run` 事件及稳定的 `runId`。可用以下接口查询运行审计记录：

```bash
curl "http://localhost:8080/api/v1/agent-runs?limit=20"
curl "http://localhost:8080/api/v1/agent-runs/{runId}"
```

回放只保存工具 Action、Observation、策略拒绝、错误摘要和最终回答，不保存模型隐藏思维链。

## 项目结构

```
StockWise/
├── README.md
├── docs/
│   ├── 00-需求规格说明书-v3.md              # 当前需求唯一真源
│   ├── 08-开发指挥Prompt.md                 # 开发指挥 Prompt
│   ├── 后端架构分析.md                      # 后端现状分析
│   ├── ReAct-Skill-记忆优化方案.md          # Agent 优化方案
│   └── 16-个人网站与Agent服务规划.md        # 个人网站、双 Agent、Skill 外网服务与文档中心规划
├── db/
│   └── schema.sql               # 数据库 DDL
├── deploy/
│   └── docker-compose.yml       # Docker 部署
├── stockwise-backend/           # Java Agent、RAG、记忆与业务 API
├── stockwise-frontend/          # 独立Nginx静态前端与前端契约测试
├── stock-wrapper/               # Node.js HTTP 包装层，与 stock-analysis-skill 同镜像
└── diagrams/
    ├── StockWise系统总架构.drawio
    ├── 后端现状架构图.drawio
    ├── Agent与记忆目标架构.drawio
    └── 整体调用逻辑.drawio
```

`stock-analysis-skill` 源码位于工作区同级的 `skills/stock-analysis-skill/`，Docker 构建时与 `stock-wrapper` 一起打入 Node 镜像。

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
