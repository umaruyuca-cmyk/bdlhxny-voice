# 数据库脚本目录

本目录是仓库唯一的数据库脚本位置。这里按“新项目全量建库”维护，
不保留 Flyway 自动迁移。所有脚本均需由开发人员或
数据库管理员显式执行；任何应用服务启动时都不会自动建表、写入种子数据或执行迁移。

## 目录说明

- `postgresql/bootstrap.sql`：角色和 Schema 的前置初始化脚本，使用数据库管理员角色执行。
- `postgresql/schema/`：当前 Java Data Plane 与 Memory Service 所需的全量表、索引和约束。
- `postgresql/seed/registry.sql`：当前 Registry 的全量种子；仅在执行完对应 Schema 后执行。
- `postgresql/upgrades/`：已有库的手工增量 ALTER（按文件名日期执行）；新库不要跑 upgrades，直接用 schema 全量。
- `mysql/user_schema.sql`：认证和用户模块的全量表与初始角色权限数据。

## 开发环境全量重建顺序

1. 清空并重新创建目标开发数据库。
2. 使用管理员角色执行 `postgresql/bootstrap.sql`。
3. 使用 `bdlh_runtime_data` 角色执行 `postgresql/schema/platform_contract.sql`、`runtime_core.sql`、`task_messaging.sql`、`notifications.sql`、`run_projection.sql`、`registry.sql` 和 `financial_user_data.sql`。
4. 使用 `bdlh_memory_service` 角色执行 `postgresql/schema/memory_service.sql`。
5. 使用 `bdlh_runtime_data` 角色执行 `postgresql/seed/registry.sql`。
6. 如需认证和用户模块，再按需要执行 `mysql/user_schema.sql`。

## 已有库增量

若云库已有 `runtime.chat_session` 但缺少暂停/实体列，手工执行：

`postgresql/upgrades/20260817_chat_session_pause_and_entity.sql`

若缺少用户金融资料表，手工执行：

`postgresql/schema/financial_user_data.sql`（`CREATE IF NOT EXISTS`，可重复执行）

应用仅假定上述数据库对象已经存在；缺表或缺少权限时应直接报错，不在启动期修复。
