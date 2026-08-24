# sentinel-console（Sentinel 前端）

独立 Nginx 静态前端，无构建工具链（原生 HTML/CSS/JS + ECharts CDN）。浏览器只访问同源 `/api/`；代理层按领域分发到 Java 数据面与 Python Agent 引擎。

> 产品形态以 [`docs/architecture/00-Sentinel产品设计与架构.md`](../docs/architecture/00-Sentinel产品设计与架构.md) §7 为准：
> **目标首页为看护 dashboard**（持仓概览 / 事件时间线 / 活跃监视 / 追问抽屉，T3 实施）；
> 现行入口 `/agent`（chat.html）在 T3 收敛为追问抽屉与会话视图组件。

## 本地前后端联调

先启动 Java 数据面（端口 `8081`）和 Python 引擎（端口 `8090`），再在本目录执行：

```powershell
npm run dev
```

本地页面：`http://127.0.0.1:8082/`

开发服务器把认证和用户领域 API 代理到 Java，把聊天与会话 API 代理到 Python。如需临时连接其他服务：

```powershell
$env:BDLH_RUNTIME_BACKEND_URL="http://127.0.0.1:8081"
$env:BDLH_RUNTIME_ANALYSIS_URL="http://127.0.0.1:8090"
npm run dev
```

## 对接文档

- [`CHAT_INTEGRATION.md`](CHAT_INTEGRATION.md) — 对话页与后端对接（描述现行实现；T3 契约切换后按设计文档 §6.2 / §7 重写）
- [`API_INTEGRATION.md`](API_INTEGRATION.md) — 页面路由与 API 契约（同上）

## 测试

```bash
npm test
```

## 构建和启动

```bash
docker build -t bdlh-runtime-console:1.0.0 .

docker run -d \
  --name bdlh-runtime-console \
  --restart unless-stopped \
  --network host \
  bdlh-runtime-console:1.0.0
```

公网边缘 Nginx 将主域名转发到仅监听回环地址的前端容器；更新前端只需重建并替换该容器。完整域名、证书、路由与端口收口步骤见 [`deploy/DOMAIN_DEPLOYMENT.md`](../deploy/DOMAIN_DEPLOYMENT.md)。
