# web（对照评测展示站）

纯静态 Nginx 展示站，无构建工具链、无后端依赖：`/` 重定向到 `/docs/` 文档站（架构概览、Agent 循环、工具目录与治理、三种架构对照、评测口径、固定题库、评测结果）。

该模块只提供公开静态结果页面，不包含运行 API、模型密钥或自由输入入口。

## 本地预览

```powershell
npm run dev
```

打开 `http://127.0.0.1:8082/docs/`。

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
