# web（实验结果与原始证据展示站）

纯静态站点（Nginx 容器或 `npm run dev` 本地服务），无构建工具链。公开站收敛为五页（信息架构 v3，顺序固定）：

| 路由 | 页面 | 职责 |
|---|---|---|
| `/` | 系统总览 | 系统定位、正式实验状态、端到端流程、系统构成（非成绩） |
| `/results/` | 实验结果 | 第一核心页：批次/实验/变体/场景/状态筛选、固定条件、样本规模、核心指标、变体对比、分场景结果、失败类型、代表案例 |
| `/evidence/` | 原始证据 | 第二核心页：运行索引（六维筛选 + 分页）；`/evidence/run/?id=<run_id>` 为单次运行 11 段证据链 |
| `/system/` | 执行逻辑 | 一次运行的完整链路（每步输入/模块/规则/输出/证据）、模块关系与公私边界 |
| `/methodology/` | 测试逻辑 | 实验设计口径、实验模板清单、指标定义（全站唯一版本）、有效/无效运行口径 |

本站零后端依赖：不反代任何 API、无登录/退出、无发起实验/我的测试/匿名试用入口；数据页面只经统一适配层 `public/docs/showcase-data.js`（`loadIndex` / `loadBatch` / `loadRun`）读取 `public/showcase-data/` 下的公开快照（发布器 `scripts/publish-showcase.mjs` 的产物）。尚无正式发布批次时，结果与证据页保持真实空状态。

静态资产位于 `/docs/`（`docs.css` / `docs.js` / `showcase-data.js` / `home.js`）；旧模块地址（`/experiment/*`、`/test/*`、`/showcase/*`、`/context/*`、`/judging/*`、`/engine/*`、`/ops/*`、`/tools/*`、`/cases/*`、`/about/*`、`/assets/*`、`/docs` 等）由 `scripts/redirect-map.mjs` 按「内容唯一归属」301 到五页（nginx 与 dev-server 同一映射）。

该模块不含模型密钥或自由输入入口。

## 本地预览

```powershell
npm run dev
```

打开 `http://127.0.0.1:8082/`（纯静态服务，无任何后端代理）。

## 测试

```bash
npm test          # 结构/公开契约/结果与证据契约/Schema/发布管线
npm run test:visual  # 视觉冒烟(3 档宽度,需 playwright;先 npm run dev)
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
