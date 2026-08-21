# BDLH Agent Runtime Frontend

独立 Nginx 静态前端。正式入口为 `public/index.html`，浏览器只访问同源 `/api/`；代理层按领域分发到 Java 用户服务和 Python Cognitive Orchestrator。

## 本地前后端联调

先启动 Java Backend（端口 `8081`）和 Python Orchestrator（端口 `8090`），再在本目录执行：

```powershell
npm run dev
```

本地页面：

```text
http://127.0.0.1:8082/
```

首页的 `/agent` 进入统一金融助手，请求由 Python Cognitive Orchestrator
（`cognitive_finance`）处理。`/workspace` 永久重定向到 `/agent`；旧双模式页面已删除。

Skill 目录从 `public/skills/registry.json` 读取脱敏注册清单，当前展示 Stock Skill 与 Web Search Skill。

开发服务器把认证和用户领域 API 代理到 Java，把聊天与会话 API 代理到 Python。如需临时连接其他服务：

```powershell
$env:BDLH_RUNTIME_BACKEND_URL="http://127.0.0.1:8081"
$env:BDLH_RUNTIME_ANALYSIS_URL="http://127.0.0.1:8090"
npm run dev
```

## 测试

```bash
npm test
```

## 构建和启动

在本目录执行：

```bash
docker build -t bdlh-runtime-console:1.0.0 .

docker run -d \
  --name bdlh-runtime-console \
  --restart unless-stopped \
  --network host \
  bdlh-runtime-console:1.0.0
```

访问：

```text
https://bdlhxny.com/
```

公网边缘 Nginx 将主域名转发到仅监听回环地址的前端容器。更新前端时只需要重新构建和替换 `bdlh-runtime-console` 容器，不需要重新打包或重启 Backend JAR。完整域名、证书、路由和端口收口步骤见 [`deploy/DOMAIN_DEPLOYMENT.md`](../deploy/DOMAIN_DEPLOYMENT.md)。
