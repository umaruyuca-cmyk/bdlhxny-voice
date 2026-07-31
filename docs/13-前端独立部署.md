# StockWise Frontend 独立部署

> 目标：前端 HTML/CSS/JavaScript 独立发布，修改页面时不重新构建或部署 Java Backend。

## 1. 部署拓扑

```text
浏览器
→ http://118.25.178.86:8082
→ stockwise-frontend（Nginx）
   ├→ /、/stockwise-chat.html：静态页面
   └→ /api/*：反向代理到 127.0.0.1:8081
      → stockwise-backend
```

前端继续使用相对路径 `/api/v1/...`，浏览器始终访问同一来源，因此不需要放宽 Backend CORS。

## 2. 前端目录

```text
stockwise-frontend/
├── public/
│   └── stockwise-chat.html
├── legacy/
│   ├── stock-agent.html
│   └── stockwise-chat-demo.html
├── test/
│   └── frontend-contract.test.js
├── Dockerfile
├── nginx.conf
└── package.json
```

生产镜像只复制 `public/`。`legacy/` 用于保留历史页面，不进入镜像。

## 3. 测试

```bash
cd stockwise-frontend
npm test
```

测试固定正式页面必须：

- 使用 POST `/api/v1/chat/stream`。
- 使用 `ReadableStream` 消费 SSE。
- 不在 URL 中传递 `userId` 或消息正文。
- 知识和 Agent Run 接口继续使用同源 `/api/v1/`。

## 4. 构建与启动

```bash
cd stockwise-frontend
docker build -t stockwise-frontend:1.0.0 .

docker run -d \
  --name stockwise-frontend \
  --restart unless-stopped \
  --network host \
  stockwise-frontend:1.0.0
```

检查：

```bash
curl --fail http://127.0.0.1:8082/
curl --fail http://127.0.0.1:8082/api/v1/agent-runs?limit=1
```

## 5. 独立发布

只修改前端时：

```bash
cd stockwise-frontend
docker build -t stockwise-frontend:1.0.1 .
docker rm -f stockwise-frontend
docker run -d \
  --name stockwise-frontend \
  --restart unless-stopped \
  --network host \
  stockwise-frontend:1.0.1
```

这一过程不修改、不重启 `stockwise-backend`。

## 6. 安全要求

- 只公开前端8082，Backend8081绑定到 `127.0.0.1`。
- Nginx 必须关闭代理缓冲，保证 SSE 实时下发。
- 不把数据库密码、Wrapper Token 或模型密钥写入前端代码。
- 域名 HTTPS 可用后，由正式入口代理前端，并关闭公网8082。
