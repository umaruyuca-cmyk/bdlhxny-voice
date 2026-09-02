# showcase-data 数据契约

公开五页(信息架构 v3)只读 `web/public/showcase-data/` 下的静态数据;
发布脚本(`web/scripts/publish-showcase.mjs`)产出的文件必须通过本目录 schema 校验,
前端统一经 `public/docs/showcase-data.js` 适配层消费(页面不自行解析字段)。

## 三个 schema

| 文件 | 产物 | 消费方 |
|---|---|---|
| `index.schema.json` | `showcase-data/index.json`(正式批次索引 + 最新批次门槛状态) | `/`(系统总览)与 `/results/`(经 `loadIndex`) |
| `batch-report.schema.json` | `showcase-data/batches/{id}/report.json`(批次报告;`purpose`/`experiment_name` 为可选扩展字段) | `/results/`(经 `loadBatch`) |
| `run.schema.json` | `showcase-data/runs/{id}.json`(单次运行公开工件;`started_at`/`config`/`config_hash` 与工具调用 `arguments`/`duration_ms` 为可选扩展字段,旧版工件缺失时页面显示「未记录」) | `/evidence/` 与 `/evidence/run/`(经 `loadRun`) |

## 关键约定

- **未运行 = null**:所有数量/结果字段允许 `null`,页面渲染为「未运行」;
  不得用设计样例数字或估算值填充(showcase 文档 §2.4);
- **validity 取值**:`VALID` / `INVALID` / `UNCLASSIFIED`。有效性分类(P3-1)落地前
  发布脚本统一写 `UNCLASSIFIED`,首页不把该批次当正式结果;
- **status 取值**:`COMPLETE` / `FAILED` / `INVALID` / `CANCELLED` / `PENDING_JUDGMENT` / `NOT_RUN`
  (评测文档 §7.1 运行状态);
- **两类实验不混表**:`experiment_type` 区分 `agent-implementation` 与 `context-strategy`
  (评测文档 §2);
- **null 语义在 `type` 数组里表达**(如 `["integer","null"]`),不使用自定义关键字。

## 禁止字段(发布硬校验)

公开工件不得包含以下字段名(`validate.mjs` 的 `scanForbidden` 深度扫描,
命中即发布失败;schema 全层 `additionalProperties: false` 双保险):

`system_prompt` / `api_key` / `authorization` / `x-internal-token` / `password` /
`secret` / `cookie` / `session_token`

未脱敏用户数据、内部地址与完整工具原文同样禁止(发布脚本负责不投影这些字段)。

## 校验器用法

```js
import { loadSchema, validate, scanForbidden } from "./validate.mjs";

const schema = await loadSchema("batch-report");
validate(payload, schema);            // 不合 schema 抛 ValidationError
const hits = scanForbidden(payload);  // 返回命中的禁止字段名数组,应为空
```
