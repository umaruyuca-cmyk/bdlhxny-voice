# 20260818 — run_projection 增加 L0 checkpoint 列

## 变更摘要

- `postgresql/schema/run_projection.sql` 为 `runtime.run_projection` 增加 `checkpoint_id`（VARCHAR）与 `cognitive_checkpoint`（JSONB）。
- 背景：Python 编排已把 Cognitive L0 checkpoint 写入 Run State，但 Java Run Projection 翻译层没有对应列，生产 Pause/Resume 会丢失三游标。

## 前置条件

- **空库全量**：按下方顺序重建（推荐）
- 已按上一份基线建好的库：本仓库约定不做增量 upgrade。需要该列时按全量脚本重建 `runtime` schema，或由运维按全量 DDL 对齐（应用启动不执行 DDL）

## 执行顺序

与 [20260817_补齐portfolio_transactions表.md](./20260817_补齐portfolio_transactions表.md) 相同：

```text
1. postgresql/bootstrap.sql
2. postgresql/schema/platform_contract.sql
3. postgresql/schema/runtime_core.sql
4. postgresql/schema/task_messaging.sql
5. postgresql/schema/notifications.sql
6. postgresql/schema/run_projection.sql
7. postgresql/schema/registry.sql
8. postgresql/schema/financial_user_data.sql
9. postgresql/schema/memory_service.sql
10. postgresql/seed/registry.sql
```

可选 MySQL：`mysql/user_schema.sql`

## 验收

- `\d runtime.run_projection` 能看到 `checkpoint_id` 与 `cognitive_checkpoint`
- `PUT/GET /internal/v1/runtime/runs/{runId}/projection` 往返携带 `checkpointId` / `cognitiveCheckpoint`
