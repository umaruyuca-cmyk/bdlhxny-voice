# 后续数据库变更

数据库初始化完成后，新增字段、索引、约束或数据修复脚本放在本目录，由维护者手动执行。

文件名使用日期和普通说明：

```text
20260821-add-run-cancel-reason.sql
20260825-add-context-cache-index.sql
```

每份脚本必须：

1. 使用 `BEGIN` 和 `COMMIT`；
2. 设置合理的 `lock_timeout` 和 `statement_timeout`；
3. 在成功结束前写入 `touchstone.database_changes`；
4. 明确对现有数据的处理方式；
5. 说明是否需要先停止 Data 或 Engine 服务；
6. 执行前完成备份，失败后不得直接修改已执行脚本。

示例登记语句：

```sql
INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260821-add-run-cancel-reason.sql', '为运行记录增加取消原因');
```

本目录不使用 Flyway 版本号，也不会被应用自动扫描。

## 脚本依赖顺序（2026-08-22 更新）

- `20260822-tool-catalog-extended-fields.sql`：**仅用于 2026-08-22 之前初始化的
  历史库**。此日期起 `setup/init.sql` 建表已直接包含评测轴三列，新库不再执行。
- `20260822-generic-mock-tools.sql`：依赖上述三列存在（历史库须先执行
  extended-fields；新库由 init.sql 提供）。内部两段冻结集大 INSERT 已带
  `ON CONFLICT DO NOTHING`，可安全重跑。
- `20260822-generic-phase1-cases.sql`：依赖 generic-mock-tools 的 96 个通用工具
  行存在（用例金标引用工具名）。
- `20260821-long-context-cases.sql`、`20260822-fixture-negative.sql`、
  `20260822-fixture-deep-search.sql`：相互独立，任意时间执行；均已幂等可重跑。
- `20260825-two-track-experiments.sql`：写入压缩/对比双轨实验结构与 20 条 cmp-* 用例。
- `20260826-fix-comparison-mock-and-deps.sql`：依赖上一脚本已写入 cmp-*；校正 Mock
  匹配参数、四字段依赖结构、登记 `cmp-fixtures-v2` 与内容哈希。可由
  `python -m` / `engine/scripts/generate_cmp_fix_sql.py` 从过渡层数据重新生成。

新库完整初始化顺序见 `../setup/README.md` 的《新库需要的后续变更脚本》。

## 脚本依赖顺序（2026-08-26 更新）

本日四个脚本彼此独立、均为增量/幂等，可按任意顺序分别执行（每个脚本自带
BEGIN/COMMIT，失败整体回滚）。统一规范：执行前备份，执行后跑脚本尾部核验 SQL；
应用启动、容器启动与测试不会自动执行迁移。

- `20260826-run-config-snapshot.sql`：独立增量 DDL（run_batches / agent_runs /
  test_jobs 增列与索引、native-matrix 执行范围），任意时间执行；历史行保持
  NULL，不回填。DDL 用 IF NOT EXISTS + 末尾 database_changes 带
  `ON CONFLICT (script_name) DO NOTHING`，可安全重跑。
- `20260826-write-confirmations.sql`：独立新建 write_confirmations 表（写操作确认
  记录，运行/工具/规范化参数绑定、单次消费）。CREATE TABLE IF NOT EXISTS + 末尾
  `ON CONFLICT (script_name) DO NOTHING`，可安全重跑。
- `20260826-scenario-pack-finance-marker.sql`：独立新建 scenario_packs 表并登记
  finance 可选场景包（默认关闭）。CREATE TABLE IF NOT EXISTS + scenario_packs 用
  `ON CONFLICT (pack_id)`、database_changes 用 `ON CONFLICT (script_name)`
  DO NOTHING，可安全重跑；不改动任何既有金融用例或工具行。
- `20260826-fix-comparison-mock-and-deps.sql`：**依赖 20260825 已写入的 cmp-* 用例**，
  校正 Mock 匹配参数、四字段依赖结构，登记 cmp-fixtures-v2 与内容哈希；末尾
  database_changes 已补 `ON CONFLICT (script_name) DO NOTHING`，可由
  `engine/scripts/generate_cmp_fix_sql.py` 从过渡层数据重新生成后重跑。DDL 锁等待
  已放宽到 60s 以适配 Data 服务在线场景。

## 2026-08-27 旧实现清理

- `20260827-remove-legacy-agent-modes.sql`：删除停用的多 Agent 实现目录、版本外键和
  旧实验范围，只保留当前统一原生 Tool Calling 底座需要的模板实验数据。执行前备份，
  建议低峰期运行；脚本完成后按末尾核验 SQL 确认旧目录表不存在。

## 2026-08-28 批次报告持久化

- `20260828-batch-report-column.sql`：`run_batches` 增加 `report JSONB NOT NULL
  DEFAULT '{}'`。**注意:脚本本体无 BEGIN/COMMIT 与 database_changes 登记**
  (早于目录规范收紧),执行时应在外层单事务中包裹并补登记。
  本地开发库于 2026-08-31 补执行补登记(此前 `RunRepository` 的报告读写
  在该库一直走本地工件兜底路径)。

## 2026-08-30 上下文记忆工作台

- `20260830-context-memory-workbench.sql`：新增 `context_sessions`、`session_events`、
  `context_memory_segments`、`context_artifacts`，并扩展既有 `context_builds` 支持
  “先构建上下文、后关联 Agent 运行”。包含每账号/Session 单活跃构建和幂等唯一索引。
  脚本不导入冻结 JSON；固定实验继续走文件只读适配器，生产会话走数据库。
- `20260830-context-artifact-memory-segments.sql`：`context_artifacts` 增加
  `memory_segments` 明细快照列(JSONB 数组,不回填),Data Service Store 下工件重读
  可还原"历史摘要复用"明细。依赖主脚本已执行。
- `20260830-context-build-agent-run.sql`：`context_builds` 增加 `agent_run_snapshot`
  (JSONB),承载"一次构建一次 Agent 运行"的运行快照终态。依赖主脚本已执行。
- `20260830-context-access-grants.sql`：P1 细粒度 RBAC——新增
  `context_access_grants` 跨所有者工件读取授权表(scope 仅 ARTIFACT_READ,
  可选绑定单个 build_id,NULL=全部构建;禁止自我授权;撤销后可重授);
  审计复用既有 `audit_log`,本脚本不建审计表。
- `20260830-context-access-grants-nulls-unique.sql`：**修正上一脚本的唯一索引**
  (PostgreSQL 默认把 NULL 视为互异,build_id 为空的重复全局授权不会被拒);
  以 `NULLS NOT DISTINCT` 重建活跃授权索引(PG 15+)。必须在授权脚本之后执行。
- `20260830-context-analysis-jobs.sql`：P2 定时分析——新增
  `context_segment_quality_checks`(摘要段语义评审结果,verdict 含 ERROR=
  评审失败不伪造通过)与 `context_analysis_runs`(每次分析运行的状态与报告
  JSONB:阈值分组对照/成本收益/相关性)。依赖授权脚本的账号外键,任意时间执行。
