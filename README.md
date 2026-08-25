# Sentinel —— 主动式持仓看护 Agent

> 一个 7×24 盯着你的持仓、出事了会主动来找你的投资陪护 Agent。
> 监视优先、对话次之：事件驱动主动解读，通知之后可以追问；问答能力完整保留。
> 只读红线：不做交易、不出具投资适当性结论。

**产品设计与架构唯一真源：[docs/architecture/00-Sentinel产品设计与架构.md](docs/architecture/00-Sentinel产品设计与架构.md)**（2026-08-18 全新设计，旧设计文档已整体清除，Git 历史可追溯）。实施执行：[docs/prompts/00-Sentinel实施Prompt.md](docs/prompts/00-Sentinel实施Prompt.md)。

## 架构速览

```text
事件源（价格轮询 / 晨报定时 / 演示注入）
        ↓ WatchEvent（边沿触发 + 去重幂等）
唤醒调度 → 上下文组装（持仓 + 画像 + 目标记忆）
        ↓
   Agent 引擎（问答与看护共用）
   统一工具目录（本地 pydantic + MCP）→ 工具装载 scoped | tool search
   → LLM 自主 tool calling 循环 → 每次调用过治理中间件（只读/权限/预算/审计）
        ↓
结构化事件解读 → 通知中心 → 追问（携带事件上下文进入问答链路）
```

核心设计原则：**模型提议，代码裁决**——路由与语义判断交给模型（embedding 快路径 + tool calling），权限与边界由代码强制（治理中间件 + 场景化工具装载）。

## 技术栈

- **Agent 引擎**：Python 3.11+ / FastAPI / LangGraph（`sentinel-engine`，端口 8090）；LLM 走 OpenAI 兼容接口（默认智谱 GLM）；Qwen embedding 做语义路由与工具检索
- **数据面**：Java 17 + Spring Boot（`sentinel-data`，端口 8081）：认证、持仓、风险画像、持久化真源
- **前端**：Nginx 静态站（`sentinel-console`）：看护 dashboard + 追问抽屉 + 契约测试
- **外部能力**：MCP（akshare-one / cn-financial）+ 受控 Web 检索（`sentinel-search`）
- **存储**：PostgreSQL 16（业务 / 运行时 / 目录）+ MySQL（身份权限）；RocketMQ 可选（Outbox 模式，消费者幂等）
- **部署**：Docker Compose 一键起全栈

## 快速开始

1. 复制 [`deploy/.env.example`](deploy/.env.example) 为 `deploy/.env`，按中文注释填写（`.env` 不入库）
2. 一键起全栈：

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

本机直跑开发：

```powershell
# Agent 引擎
Set-Location sentinel-engine
uv sync --extra dev
uv run pytest -q
uv run uvicorn bdlh_runtime.main:app --reload --host 127.0.0.1 --port 8090

# 数据面（首次先复制 application.example.yml 为 application.yml 并按本机改配置）
Set-Location sentinel-data
mvn spring-boot:run
```

## 项目结构

```text
├── docs/                               # 00-仓库文件管理树（文件归属规则）
│   ├── architecture/00-…产品设计与架构  # 唯一设计真源
│   └── prompts/00-…实施Prompt          # 实施执行真源（工单集）
├── sentinel-engine/          # Python：Agent 引擎 + 看护环 + 工具目录 + 治理
├── sentinel-data/                  # Java：数据面（认证 / 持仓 / 画像 / 持久化）
├── sentinel-console/               # Nginx 静态前端与契约测试
├── sentinel-memory/                # L3 语义记忆独立服务
├── sentinel-search/            # 公开资料检索封装
├── db/                                 # 空库全量 schema 与 seed；应用启动不执行 DDL
└── deploy/                             # Docker Compose、Nginx 与部署配置
```

## 分支管理

单人开发 `main` + `dev` 两分支：日常直接在 `main` 提交；`dev` 仅在需要隔离验证时使用。

## 实施状态（2026-08-19）

T0–T4 已按 [实施 Prompt](docs/prompts/00-Sentinel实施Prompt.md) 全部收口：看护环、统一工具目录与治理中间件、SSE 契约 v2、看护首页与追问抽屉、演示 compose（console + `demo_sentinel.sql`）、演示注入与自动化彩排均已落地。

- 演示入口：品牌落地 `http://127.0.0.1:8082/`；看护首页（P1）`/dashboard`；会话入口 `/agent`
- 对接文档：[sentinel-console/CHAT_INTEGRATION.md](sentinel-console/CHAT_INTEGRATION.md)、[API_INTEGRATION.md](sentinel-console/API_INTEGRATION.md)
- 演示注入：`.\scripts\demo-inject.ps1`；自动化七步彩排：`.\scripts\demo-rehearse.ps1`（现场浏览器走查与 `recordings/` 成片由操作者补档，不入库）
- 与设计文档的实现偏差见设计文档对应章节脚注（不以本 README 另开决策）

Python 测试在部分 Windows 环境请用 `uv run python -m pytest -q`（见实施 Prompt WO-T0-1）。
