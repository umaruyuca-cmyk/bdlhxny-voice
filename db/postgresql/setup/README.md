# 新数据库初始化

本目录的 `init.sql` 是唯一初始化入口，由维护者手动执行一次，应用启动不会自动运行。
它由原 01–08 八份脚本按序合并而成，每段保留独立事务并在成功后写入
`touchstone.database_changes`（共 8 段登记）。使用 `ON_ERROR_STOP=1` 执行时失败即停，
已成功提交的段不会因后续段失败而回滚——重跑前先按登记确认进度。

## 本地 Docker 执行

先只启动 PostgreSQL：

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d postgres
```

在仓库根目录执行：

```powershell
Get-Content -Raw db/postgresql/setup/init.sql |
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres `
    sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

初始化完成后再启动其他私有服务：

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d data engine web
```

## 托管 PostgreSQL 执行

在本机安装 `psql`，把连接串放入本次终端的专用环境变量：

```powershell
$env:TOUCHSTONE_PG_URL = 'postgresql://user:password@host:5432/database?sslmode=require'

psql $env:TOUCHSTONE_PG_URL -v ON_ERROR_STOP=1 -f db/postgresql/setup/init.sql
```

不要把真实连接串写入仓库文件或命令记录文档。

## 执行后确认

```sql
SELECT script_name, description, applied_at, applied_by
FROM touchstone.database_changes
ORDER BY applied_at;
```

正常结果应该有八行（每段一行）。如果不足八行，说明有段未执行成功，
处理失败原因后不能直接启动 Data 服务。

## 脚本分段内容

| 段 | 原脚本 | 作用 |
|---:|---|---|
| 1 | `01-create-base-tables` | 创建 schema、执行记录表和基础业务表 |
| 2 | `02-seed-fixed-cases` | 写入首批固定用例、默认变体和数据快照 |
| 3 | `03-create-experiment-trace-tables` | 创建上下文策略、调用、指标和发布表 |
| 4 | `04-seed-context-catalog` | 写入四种上下文策略 |
| 5 | `05-create-execution-detail-tables` | 创建守卫拦截明细和模型输入消息快照表 |
| 6 | `06-create-accounts-tables` | 创建所有者账号、登录会话和审计表 |
| 7 | `07-create-tool-catalog-tables` | 创建工具目录表并写入操作证、工具集、能力和技能 |
| 8 | `08-seed-tool-fixtures` | 写入 A/B 评测冻结工具返回（ab-eval 数据集） |

## 新库需要的后续变更脚本

`init.sql` 只建立基础结构：18 道首批用例、金融 16 工具与 `ab-eval` 冻结集。
以下功能数据自 2026-08-22 起通过 `../changes/` 脚本提供，且**相关代码已依赖它们**
（data 服务的 `/internal/v1/tool-catalog` 直接读取 `tool_capabilities` 的
`side_effect/requires_confirmation/risk_level` 三列；该三列已合入 init.sql 建表语句，
新库**不需要**再执行 `20260822-tool-catalog-extended-fields.sql`——它仅用于
2026-08-22 之前初始化的历史库）。新库推荐执行链：

| 顺序 | 脚本 | 作用 | 是否必需 |
|---:|---|---|---|
| 1 | `../changes/20260822-generic-mock-tools.sql` | 96 个通用 Mock 工具 + mock-eval-v1/负例两冻结集 | 必需（tool-catalog 三列的目录数据） |
| 2 | `../changes/20260822-generic-phase1-cases.sql` | 首批 72 道 gt8-* 通用目录用例 | 依赖 1 |
| 3 | `../changes/20260821-long-context-cases.sql` | 6 套 ctx-* 长上下文压缩对照用例 | 需要压缩对照时 |
| 4 | `../changes/20260822-fixture-negative.sql` | 金融负例集 ab-eval-negative-v1 + 8 道负例 | 需要负例实验时 |
| 5 | `../changes/20260822-fixture-deep-search.sql` | ab-eval 补 research.deep_search 冻结行 | 幂等，建议执行 |
| 6 | `../changes/20260825-two-track-experiments.sql` | 模板实验任务、上下文构建与对比用例结构 | 必需 |
| 7 | `../changes/20260826-run-config-snapshot.sql` | 运行配置快照与模板标识 | 必需，依赖 6 |
| 8 | `../changes/20260826-fix-comparison-mock-and-deps.sql` | 修正对比用例 Mock 和依赖关系 | 必需，依赖 6 |
| 9 | `../changes/20260827-remove-legacy-agent-modes.sql` | 删除停用的多实现目录和约束 | 必需，最后执行 |
| 10 | `../changes/20260830-context-memory-workbench.sql` | 上下文工作台会话事件、增量摘要与冻结工件表 | 启用上下文工作台时必需 |
| 11 | `../changes/20260830-context-artifact-memory-segments.sql` | 工件 Segment 明细快照列 | 启用工作台 data-service 存储时，依赖 10 |
| 12 | `../changes/20260830-context-build-agent-run.sql` | 构建行 Agent 运行快照列 | 启用工作台"运行一次 Agent"时，依赖 10 |
| 13 | `../changes/20260830-context-access-grants.sql` 与 `20260830-context-access-grants-nulls-unique.sql` | 跨所有者工件读取授权表(P1 RBAC) | 启用跨所有者授权/运维视图时，依赖 10；两脚本按序执行 |
| 14 | `../changes/20260830-context-analysis-jobs.sql` | P2 定时分析(语义抽检结果与分析运行表) | 启用定时分析任务时，依赖 10 |
| 15 | `../changes/20260828-batch-report-column.sql` | 批次执行报告落库(`run_batches.report`) | 需要批次报告数据库持久化时；独立脚本，任意时间执行(需在外层事务中补登记) |

不执行第 1 项时，题库只有 18 道基础用例、冻结集只有 `ab-eval`，
`/lab` 的通用工具勾选页与 `gt8-*` 用例均不可用。

## 托管 PostgreSQL 的权限提示

`init.sql` 与全部 changes 脚本不包含任何 `GRANT`：本地 Docker 路径下
`POSTGRES_USER` 与 data 服务使用同一数据库属主用户，无需额外授权。托管
PostgreSQL 场景若用管理员用户执行初始化、而 data 服务使用独立应用用户连接，
必须另行授权，否则 data 服务启动后所有查询都会因无权限失败：

```sql
GRANT USAGE ON SCHEMA touchstone TO <应用用户>;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA touchstone TO <应用用户>;
ALTER DEFAULT PRIVILEGES IN SCHEMA touchstone
  GRANT SELECT, INSERT, UPDATE ON TABLES TO <应用用户>;
```

## 创建初始所有者账号

`init.sql` 不写入任何账号或密码。首个所有者账号由维护者在目标数据库上手动
创建，密码通过变量或交互输入，不进入 Git：

```sql
\set owner_password '请替换为强密码'
INSERT INTO touchstone.accounts (id, username, display_name, password_hash)
VALUES (gen_random_uuid(), 'owner', '项目所有者',
        crypt(:'owner_password', gen_salt('bf', 12)));
```

登录由私有运行服务负责：校验 `password_hash`、签发随机会话令牌，数据库只保存令牌
的 `sha256:<hex>` hash。仓库不保存密码、明文令牌或任何账号凭证。

## 注意事项

- `init.sql` 只用于一个尚未建立 Touchstone 表的新数据库；
- 不要在已初始化的数据库上重复执行 `init.sql`；
- 已投入使用的数据库发生变化时，在 `../changes/` 新增脚本，不回改 `init.sql`；
- 正式环境执行前先备份，并确认连接的是目标数据库。
