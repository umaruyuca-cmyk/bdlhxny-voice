# Agent 实现方式对照评测系统

本仓库只做一件事：让相同模型在相同固定问题、相同上下文和相同冻结工具数据下，分别使用不同 Agent 实现方式运行，并保存可以复查的过程和结果。

长期开发与发布分支名为 `touchstone`(历史沿用,与展示层品牌无关)。旧聊天产品、主动看护、消息队列、独立记忆服务和真实外部工具接入不属于本系统。

## 模块

```text
engine/  私有运行 API、Agent 对照运行器、上下文构建与评测
data/    固定题库、版本、批次、运行、上下文明细和评测结果
web/     公开静态结果站；浏览不会调用模型
deploy/  本地、云端和纯公开站三种 Compose 配置
docs/    按产品、架构、上下文、评测、展示和开发实施分类的设计文档
db/      PostgreSQL 总体设计、手动初始化和变更脚本、查询示例
```

PostgreSQL 是唯一数据库。当前不需要向量数据库：固定问题和上下文都按明确编号、版本和来源读取，不做开放式语义检索。以后只有出现大量非结构化资料检索需求时，才单独评估 pgvector。

## 本地启动

```powershell
Copy-Item deploy/.env.example deploy/.env
# 填写 deploy/.env 中的数据库、服务令牌和模型密钥
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d postgres
```

数据库不会由 Data 服务自动初始化。首次启动必须按照
[`db/postgresql/setup/README.md`](db/postgresql/setup/README.md) 手动执行初始化脚本
`init.sql`（单一入口，含全部建表与种子数据），确认完成后再启动应用：

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build data engine web
```

- 私有运行 API：`http://127.0.0.1:8090`
- 公开展示：`http://127.0.0.1:8082/`（旧 `/docs/` 路径已 301 跳转到新位置）
- 运行接口只接受固定 `case_id`，并要求项目所有者登录会话。

只部署公开结果站：

```powershell
docker compose -f deploy/docker-compose.public.yml up -d --build
```

云部署使用 [`deploy/docker-compose.cloud.yml`](deploy/docker-compose.cloud.yml) 和托管 PostgreSQL。带 `v*` 的标签或手动运行 `Release cloud images` 工作流会发布 engine、data、web 三个 GHCR 镜像。

## 验证

```powershell
Set-Location engine
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run python -m pytest -q

Set-Location ../data
mvn -B -ntp test

Set-Location ../web
npm test

Set-Location ..
docker compose --env-file deploy/.env.ci -f deploy/docker-compose.yml config -q
docker compose --env-file deploy/.env.ci -f deploy/docker-compose.cloud.yml config -q
docker compose -f deploy/docker-compose.public.yml config -q
```

设计入口见 [`docs/README.md`](docs/README.md)。
