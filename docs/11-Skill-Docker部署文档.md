# StockWise Skill Docker部署文档

> 部署对象：`stock-wrapper + stock-analysis-skill`  
> 镜像建议版本：`stockwise-stock-wrapper:1.1.1`  
> 更新时间：2026-07-30
>
> 临时联调说明：由于未备案域名的 HTTP/HTTPS 流量被拦截，服务器暂时将 `stock-wrapper` 映射到公网 `118.25.178.86:3001`。该入口使用明文 HTTP，只允许在安全组或防火墙中放行可信客户端 IP；域名备案或替代 HTTPS 入口可用后必须撤销公网端口映射，恢复本文默认的 `127.0.0.1:3001 + Nginx HTTPS` 拓扑。

## 1. 部署目标

在云服务器部署一个独立Node.js容器：

```text
公网443
  → Nginx TLS
  → 127.0.0.1:3001
  → stock-wrapper
  → 容器内私有stock-analysis-skill
```

核心分析源码只进入Docker构建上下文和最终镜像，不发布到公共npm。其他Agent只通过HTTPS API调用。

## 2. 当前部署边界

- Java Agent与本服务分镜像部署。
- `stock-wrapper` 和 `stock-analysis-skill` 在同一个Node.js镜像中。
- Wrapper通过受控参数数组调用CLI，不使用Shell拼接。
- Wrapper默认端口为3001。
- 云服务器宿主机不需要单独安装Node.js或npm。
- 公网只开放443，不开放3001。
- 当前鉴权为单一 `X-Internal-Token`，适用于自有或受控Agent。

## 3. 服务器要求

建议最低配置：

- Linux x86_64或arm64。
- Docker Engine 24或更高版本。
- Docker Compose Plugin 2.20或更高版本。
- Nginx。
- 已配置的HTTPS证书。
- 建议预留512MB内存，实际占用取决于并发和行情数据量。
- 能访问Skill所使用的外部行情数据源。

检查命令：

```bash
docker version
docker compose version
nginx -v
curl --version
```

## 4. 交付目录要求

Dockerfile从工作区根目录同时复制Skill和Wrapper，因此部署包至少保持以下结构：

```text
stockwise-skill-deploy/
├── .dockerignore
├── skills/
│   └── stock-analysis-skill/
│       ├── package.json
│       ├── package-lock.json
│       ├── SKILL.md
│       ├── bin/
│       ├── src/
│       ├── references/
│       ├── templates/
│       └── agents/
└── StockWise/
    └── stock-wrapper/
        ├── Dockerfile
        ├── package.json
        └── src/
```

必须从 `stockwise-skill-deploy` 根目录执行构建。不要在 `StockWise/stock-wrapper` 目录直接构建，否则Docker无法读取 `skills/stock-analysis-skill`。

部署包不得包含：

- `.env`真实密钥。
- 用户持仓。
- 运行日志。
- 历史分析结果。
- `node_modules`。
- IDE配置。

## 5. 生成生产Token

在服务器执行：

```bash
openssl rand -hex 32
```

将结果保存在服务器密钥管理或仅root可读的 `/etc/stockwise/stock-wrapper.env` 中：

```env
NODE_ENV=production
PORT=3001
INTERNAL_TOKEN=<生成的64位十六进制字符串>
STOCK_SKILL_TIMEOUT_MS=120000
STOCK_WRAPPER_MAX_CONCURRENCY=4
STOCK_WRAPPER_MAX_BODY_BYTES=65536
STOCK_WRAPPER_MAX_OUTPUT_BYTES=10485760
```

设置权限：

```bash
chmod 600 /etc/stockwise/stock-wrapper.env
```

要求：

- 至少32个随机字节。
- 环境文件权限设置为0600。
- 不提交到Git。
- 不写入Dockerfile。
- 不通过URL传递。
- 不出现在Nginx访问日志中。

## 6. 构建镜像

进入部署包根目录：

```bash
cd /opt/stockwise-skill-deploy
```

构建：

```bash
docker build \
  --pull \
  -f StockWise/stock-wrapper/Dockerfile \
  -t stockwise-stock-wrapper:1.1.1 \
  .
```

Dockerfile会执行：

1. 在构建阶段安装Skill依赖。
2. 执行Skill测试。
3. 生成npm tarball。
4. 在运行镜像中安装该tarball。
5. 启动 `stock-wrapper`。

确认镜像：

```bash
docker image inspect stockwise-stock-wrapper:1.1.1
```

## 7. 启动独立容器

推荐仅绑定本机回环地址：

```bash
docker run -d \
  --name stockwise-stock-wrapper \
  --restart unless-stopped \
  -p 127.0.0.1:3001:3001 \
  --env-file /etc/stockwise/stock-wrapper.env \
  stockwise-stock-wrapper:1.1.1
```

确认端口没有绑定到公网：

```bash
docker port stockwise-stock-wrapper
ss -lntp | grep 3001
```

正确结果应是 `127.0.0.1:3001`，不能是 `0.0.0.0:3001`。

## 8. 使用Docker Compose

现有完整StockWise Compose中，`stock-wrapper` 只通过 `expose` 提供给Docker网络内的Java后端。如果宿主机Nginx需要反向代理，还必须增加回环端口映射：

```yaml
services:
  stock-wrapper:
    build:
      context: ../..
      dockerfile: StockWise/stock-wrapper/Dockerfile
    restart: unless-stopped
    environment:
      PORT: 3001
      INTERNAL_TOKEN: ${STOCK_WRAPPER_TOKEN}
      STOCK_SKILL_TIMEOUT_MS: 120000
      STOCK_WRAPPER_MAX_CONCURRENCY: 4
    ports:
      - "127.0.0.1:3001:3001"
```

不要同时对同一个容器使用重复的宿主机端口映射。

启动：

```bash
docker compose -f StockWise/deploy/docker-compose.yml up -d --build stock-wrapper
```

如果继续使用原Compose文件中的纯内部模式，则Nginx必须加入同一Docker网络，不能通过宿主机 `127.0.0.1:3001` 访问。

## 9. 容器内部健康检查

健康检查：

```bash
curl --fail http://127.0.0.1:3001/health
```

预期：

```json
{"status":"UP","service":"stock-wrapper"}
```

就绪检查：

```bash
curl --fail http://127.0.0.1:3001/ready
```

预期：

```json
{"status":"READY"}
```

`UP` 表示HTTP进程可用，`READY` 表示容器内Skill CLI存在。业务可用性必须再执行一次带Token的分析请求。

## 10. Nginx配置

将以下配置加入 `bdlhxny.com` 的HTTPS Server块：

```nginx
location /api/v1/ {
    proxy_pass http://127.0.0.1:3001;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Internal-Token $http_x_internal_token;

    proxy_connect_timeout 5s;
    proxy_send_timeout 125s;
    proxy_read_timeout 125s;

    client_max_body_size 64k;
}
```

保留已有搜索路由：

```nginx
location = /api/search {
    # 继续代理现有web-search-wrapper。
}
```

检查并重载：

```bash
nginx -t
systemctl reload nginx
```

安全要求：

- 防火墙只开放80和443；如果已强制HTTPS，可以仅保留证书续期需要的80。
- 3001只能绑定到127.0.0.1。
- 不在Nginx日志格式中记录 `$http_x_internal_token`。
- 不把 `/health` 和 `/ready` 直接暴露公网。

## 11. 端到端验证

### 11.1 无Token必须失败

```bash
curl -i -X POST "https://bdlhxny.com/api/v1/stock/analyze" \
  -H "Content-Type: application/json" \
  --data '{"symbol":"600519","assetType":"stock"}'
```

预期HTTP 401，错误码为 `UNAUTHORIZED`。

### 11.2 有Token成功

```bash
curl --fail-with-body -X POST "https://bdlhxny.com/api/v1/stock/analyze" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Internal-Token: ${STOCK_WRAPPER_TOKEN}" \
  -H "X-Request-ID: ops-stock-smoke-001" \
  --data '{"symbol":"600519","assetType":"stock"}'
```

至少校验：

```text
success == true
contractVersion == "1.0"
data.schemaVersion == "1.1"
data.methodology.id == "stockwise-objective-analysis"
data.methodology.version == "1.0.0"
data.decisionBasis 是对象
data.dataQuality 是对象
data.asOf 非空
```

### 11.3 其他命令冒烟测试

```bash
curl --fail-with-body -X POST "https://bdlhxny.com/api/v1/sector/analyze" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: ${STOCK_WRAPPER_TOKEN}" \
  --data '{"type":"industry","limit":5}'
```

```bash
curl --fail-with-body -X POST "https://bdlhxny.com/api/v1/quant/analyze" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: ${STOCK_WRAPPER_TOKEN}" \
  --data '{"codes":["510300","159915","512100"],"benchmark":"510300"}'
```

## 12. 日志与排障

查看容器：

```bash
docker ps --filter name=stockwise-stock-wrapper
```

查看最近日志：

```bash
docker logs --tail 200 stockwise-stock-wrapper
```

持续查看：

```bash
docker logs -f --since 10m stockwise-stock-wrapper
```

排障顺序：

1. `docker ps` 确认容器运行。
2. 本机 `/health` 确认HTTP进程。
3. 本机 `/ready` 确认CLI存在。
4. 本机带Token调用业务接口。
5. `nginx -t` 确认配置。
6. 公网HTTPS调用。
7. 使用 `X-Request-ID` 对照Nginx和容器日志。

常见问题：

| 现象 | 可能原因 |
|---|---|
| 401 | 调用方Token与 `INTERNAL_TOKEN` 不一致 |
| 404 | Nginx路径或 `proxy_pass` 配置错误 |
| 429 | 达到Wrapper并发上限 |
| 502 | Skill执行失败、输出契约错误或上游行情失败 |
| 503 | CLI文件不存在或镜像构建不完整 |
| 504 | Skill执行超过120秒 |
| 公网失败但本机成功 | Nginx、证书、DNS、防火墙或代理问题 |

## 13. 升级和回滚

升级时使用新镜像标签，不覆盖旧标签：

```bash
docker build \
  -f StockWise/stock-wrapper/Dockerfile \
  -t stockwise-stock-wrapper:1.1.1 \
  .
```

升级前记录：

- 镜像ID。
- Skill版本。
- `methodology.version`。
- 冒烟测试结果。
- 部署时间。

回滚原则：

1. 停止新容器。
2. 使用上一版本镜像重新启动。
3. 保持原Token不变。
4. 重跑无Token和有Token冒烟测试。
5. 记录回滚原因和受影响requestId。

方法论版本发生变化时，必须确认调用方支持新契约后再切流。

## 14. 运维Agent交付验收清单

- [ ] Docker和Nginx版本满足要求。
- [ ] 部署目录结构正确。
- [ ] 构建日志中的Skill测试通过。
- [ ] `INTERNAL_TOKEN` 非空且未写入代码或镜像。
- [ ] 容器只绑定 `127.0.0.1:3001`。
- [ ] 防火墙未开放3001。
- [ ] `/health` 返回UP。
- [ ] `/ready` 返回READY。
- [ ] 无Token公网请求返回401。
- [ ] 有Token单标的请求成功。
- [ ] 返回Skill `schemaVersion=1.1`。
- [ ] 返回方法论和决策依据。
- [ ] Nginx日志不记录Token。
- [ ] 已保存镜像版本和回滚命令。
- [ ] 已向接入方单独安全传递Token。

## 15. 当前上线限制

本次部署可以向自有Agent和少量受控Agent开放。它还不是完整的多租户公网服务，原因是当前只有单Token鉴权。

正式面向多个客户之前，不得仅靠Nginx复制多个Token；应先在Wrapper代码中实现逐Agent鉴权、Token哈希、限流、配额、吊销和审计。
