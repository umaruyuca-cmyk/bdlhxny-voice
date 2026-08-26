# web（对照评测展示站）

纯静态站点（Nginx 容器或 `npm run dev` 本地服务），无构建工具链：公告首页、实验模块（模板中心 `/experiment/`、统一发起 `/experiment/run`、批次列表 `/experiment/batches`、批次详情 `/experiment/batch/<id>`）、我的测试 `/test/` 与数据资产/文档页面。

运行入口依赖可选反代（同源契约见 `docs/design/前后端对接文档.md`）：

- `/api/v1/public/*`（匿名测试）与所有者通道 `/api/v1/(login|logout|experiment-templates|template-batches|batches|jobs|runs)` 反代到 engine；不含 engine 的纯静态部署中，实验页提交会如实失败。
- `/experiment/batch/<id>` 由 `batch.html` 解析路径中的批次标识（nginx `try_files` 与 dev-server 同口径）。

该模块不含模型密钥或自由输入入口。

## 本地预览

```powershell
npm run dev
```

打开 `http://127.0.0.1:8082/`（dev-server 默认把 `/api/v1/` 反代到本地 engine `127.0.0.1:8090`，可用 `RUN_API_PROXY=off` 关闭）。

## 测试

```bash
npm test
```

## 构建和启动

```bash
docker build -t web:1.0.0 .

docker run -d \
  --name web \
  --restart unless-stopped \
  --network host \
  web:1.0.0
```
