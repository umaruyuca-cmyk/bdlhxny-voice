# StockWise Frontend

独立 Nginx 静态前端。正式入口为 `public/index.html`，通过同源 `/api/` 调用 StockWise Backend。

## 本地前后端联调

先以 `dev` Profile 启动本地 Backend（端口 `8080`），再在本目录执行：

```powershell
npm run dev
```

本地页面：

```text
http://127.0.0.1:8082/
```

首页进入统一工作站，支持普通问答、Stock Agent、标的选择、SSE 流式回答和运行追踪。历史页面仍保留在 `public` 供兼容测试使用，但不属于公共导航。

Skill 目录从 `public/skills/registry.json` 读取脱敏注册清单，当前展示 Stock Skill 与 Web Search Skill。

开发服务器会把 `/api/**` 流式代理到 `http://127.0.0.1:8080`。如需临时连接其他 Backend：

```powershell
$env:STOCKWISE_BACKEND_URL="http://127.0.0.1:8080"
npm run dev
```

## 测试

```bash
npm test
```

## 构建和启动

在本目录执行：

```bash
docker build -t stockwise-frontend:1.0.0 .

docker run -d \
  --name stockwise-frontend \
  --restart unless-stopped \
  --network host \
  stockwise-frontend:1.0.0
```

访问：

```text
http://118.25.178.86:8082/
```

更新前端时只需要重新构建和替换 `stockwise-frontend` 容器，不需要重新打包或重启 Backend JAR。
