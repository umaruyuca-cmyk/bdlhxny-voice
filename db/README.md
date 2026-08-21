# 数据库脚本目录

本目录是仓库唯一的数据库脚本位置。按「空库全量」维护；应用启动不执行 DDL/seed/迁移。

## 怎么执行

1. 打开 [execution/](./execution/) —— **按日期追加的执行说明**
2. 以其中**最新一份**为当前基线（见 [execution/README.md](./execution/README.md)）
3. 用**一个超级管理员**按该文件顺序跑 SQL

**当前基线：** [execution/20260817_SQL字段注释整理.md](./execution/20260817_SQL字段注释整理.md)

## 目录结构

| 路径 | 用途 |
|---|---|
| `execution/` | 每次 DB 更新追加一份执行说明（管理入口） |
| `postgresql/bootstrap.sql` | 角色与 Schema 初始化 |
| `postgresql/schema/` | 全量表结构 |
| `postgresql/seed/` | 全量种子（当前仅 Registry） |
| `mysql/user_schema.sql` | 认证/用户模块（独立 MySQL，可选） |

已删除：`postgresql/upgrades/`（全量约定下不再使用增量脚本）。

## 以后每次改库

1. 改 `schema/` / `seed/`（必要时 `bootstrap.sql`）
2. 在 `execution/` **新增** `YYYYMMDD_说明.md`（不要改旧文件）
3. 把本 README「当前基线」链接改到最新文件
