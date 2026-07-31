# StockWise 本地与云端配置

项目只使用两个环境配置：

| 配置文件 | 用途 | 启用方式 |
|---|---|---|
| `application-dev.yml` | 本地开发 | 默认启用 |
| `application-prod.yml` | 云端部署 | Compose 自动启用 |

公共业务参数放在 `application.yml`，不要在两个环境文件中重复维护。

## 本地使用

`application.yml` 默认设置：

```yaml
spring:
  profiles:
    active: dev
```

因此本地直接启动：

```powershell
Set-Location stockwise-backend
mvn spring-boot:run
```

本地 MySQL 固定为：

```text
地址：localhost:3306
数据库：platform
用户名：root
密码：root
```

接口文档：

```text
http://localhost:8080/docs
```

本地 `dev` 会使用本机数据库，同时调用以下云端能力：

```text
搜索服务：http://118.25.178.86:3002/api/search
股票服务：http://118.25.178.86:3001
Ollama：https://bdlhxny.com/ollama
前端页面：http://118.25.178.86:8082/ 或 https://bdlhxny.com/
```

聊天模型与向量模型支持独立切换，默认配置为：

```yaml
stockwise:
  ai:
    chat-provider: deepseek
  embedding:
    provider: dashscope
    base-url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api-key: ""
    model: text-embedding-v4
    dimensions: 1024
```

`chat-provider` 改为 `ollama` 可恢复旧聊天模型；`embedding.provider` 改为
`ollama` 可恢复旧向量模型。`text-embedding-v4` 固定请求 1024 维，以兼容现有
PostgreSQL pgvector 字段和索引。

若使用阿里云百炼 Workspace 专属域名，将 `base-url` 改为：

```text
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
```

## 云端使用

云端连接信息、密码和 Token 全部直接写在：

```text
stockwise-backend/src/main/resources/application-prod.yml
```

`docker-compose.cloud.yml` 已设置：

```yaml
SPRING_PROFILES_ACTIVE: prod
```

部署时只执行：

```bash
docker compose -f deploy/docker-compose.cloud.yml up -d --build
```

不再需要 `.env.cloud`、`--env-file` 或 `application-secrets.yml`。

更新代码或配置后：

```bash
docker compose -f deploy/docker-compose.cloud.yml up -d --build --force-recreate
```

验证：

```bash
docker logs --tail 200 stockwise-backend
curl --fail-with-body http://127.0.0.1:8081/actuator/health
```

云端 Scalar 文档：

```text
http://127.0.0.1:8081/docs
```

## 修改规则

1. 本地地址和账号只改 `application-dev.yml`。
2. 云端地址和账号只改 `application-prod.yml`。
3. 公共业务参数只改 `application.yml`。
4. MySQL 数据库统一使用 `platform`。
5. MySQL JDBC 的 `characterEncoding` 使用 `UTF-8`。
6. 云端数据库和 Redis 不向公网开放时，本地 `dev` 使用本机实例，不要改成云服务器公网 IP。
