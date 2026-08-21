# 20260817 — 补齐 portfolio_transactions 表

## 变更摘要

- `postgresql/schema/financial_user_data.sql` 新增 `public.portfolio_transactions` 建表语句与 `(user_id, trade_date DESC, id DESC)` 索引。
- 背景：Java 数据平面 `PortfolioTransaction` 实体与 `/api/portfolio/transactions` 查询早已引用该表，但空库全量 SQL 一直缺失 DDL，空库初始化后该接口会直接报「关系不存在」。

## 前置条件

- **空库全量**：按下方顺序重建（推荐）
- 已按上一份基线建好的库，可单独执行本文件新增的 `portfolio_transactions` 建表段（`CREATE TABLE IF NOT EXISTS` + 索引 + 注释），无需重建其他表

## 执行顺序

与 [20260817_SQL字段注释整理.md](./20260817_SQL字段注释整理.md) 相同：

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

- `\d public.portfolio_transactions` 能看到表结构与索引 `idx_portfolio_transactions_user_trade_date`
- Java 数据平面启动后 `GET /api/portfolio/transactions?user_id=...` 返回 `SUCCESS`（空列表即可），不再报错
