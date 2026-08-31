# 部署

## 本地原生启动（不走 Docker）

本地开发只做原生进程互访（隧道 → data 18081 → engine 8090 → web 8082），
镜像构建/推送在云服务器执行。模块、环境变量、端口与排查见
[`本地启动说明.md`](./本地启动说明.md)。

## 密钥管理

- `deploy/.env` 只在本机使用，已被 `.gitignore` 覆盖，**永不提交**；真实密钥
  （数据库密码、`DATA_INTERNAL_TOKEN`、`LLM_API_KEY`）建议从密码管理器取出后
  现场注入，不在工作区长期明文存放；
- 云环境密钥走托管平台的 secret 注入，不写进镜像、compose 文件或命令记录；
- 任何密钥疑似泄漏（误提交、打包、录屏、共享）立即轮换：`LLM_API_KEY` 在厂商
  控制台重置；`POSTGRES_PASSWORD` 与 `DATA_INTERNAL_TOKEN` 轮换时需同步更新
  data 与 engine 两侧环境后滚动重启；
- `.env.example` / `.env.ci` 只允许占位值。

## 本地完整环境

包含 PostgreSQL、`data`、`engine` 和 `web`：

```powershell
Copy-Item deploy/.env.example deploy/.env
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d postgres
```

第一次部署时，按照 [`db/postgresql/setup/README.md`](../db/postgresql/setup/README.md)
手动执行数据库初始化脚本 `init.sql`（单一入口，含全部建表与种子数据）。
数据库准备完成后再启动应用：

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build data engine web
```

Engine 端口默认只绑定 `127.0.0.1`。如果通过网关提供私有运行页面，网关仍需做项目所有者登录；运行接口本身已要求账号会话令牌，不应暴露给浏览器或公开站。

上下文工作台默认使用 `CONTEXT_MEMORY_MODE=legacy` 和
`CONTEXT_BUILD_STORE=file`，因此不会读取或写入生产上下文表。代码支持以下显式切换：

- `shadow + file`：生产 Session 优先读取，缺失或不可用时回退冻结 Session；构建工件仍写本地文件。
- `incremental + file`：只读取生产 Session；构建工件仍写本地文件。
- `incremental + data-service`：Session、构建状态和工件均经过 Data Service；只有数据库结构已经准备好后才能启用。

`data-service` Store 与 `legacy`/`shadow` 组合会拒绝运行，避免把冻结 Session
误写入生产数据库。

## 云环境

`docker-compose.cloud.yml` 使用已经发布的三个镜像，并连接托管 PostgreSQL。先使用
`psql` 按 [`db/postgresql/setup/README.md`](../db/postgresql/setup/README.md) 初始化托管数据库，
然后启动服务：

```powershell
docker compose --env-file deploy/.env.cloud -f deploy/docker-compose.cloud.yml up -d
```

云环境需要设置 `IMAGE_REGISTRY`、`IMAGE_TAG`、`DATABASE_URL`、`DATABASE_USER`、`DATABASE_PASSWORD`、`DATA_INTERNAL_TOKEN`、`LLM_API_KEY` 和 `GIT_COMMIT`。数据服务和运行服务应放在私有网络；只让展示站或经过登录保护的反向代理暴露公网端口。

**TLS 强制要求**：云端 web 默认 `CONSOLE_BIND=0.0.0.0` 提供的是明文 HTTP，公网流量
必须在网关/负载均衡终止 TLS 后再转发到该端口。不要把 `CONSOLE_PORT` 的明文端口
直接暴露到公网；网关需配置证书并强制 HTTP→HTTPS 跳转。

## 纯公开展示

```powershell
docker compose -f deploy/docker-compose.public.yml up -d --build
```

这个配置只有静态 Nginx，不含数据库、模型密钥、数据服务或运行 API，因此访问页面不会产生 token 消耗。

## 配置检查

```powershell
docker compose --env-file deploy/.env.ci -f deploy/docker-compose.yml config -q
docker compose --env-file deploy/.env.ci -f deploy/docker-compose.cloud.yml config -q
docker compose -f deploy/docker-compose.public.yml config -q
```
