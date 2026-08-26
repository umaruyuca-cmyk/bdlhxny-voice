-- 20260826-run-config-snapshot.sql
-- 混合路线阶段 A4:运行配置快照(RunConfig/config_hash)与实验模板标识的持久化列
--
-- 结构部分:
--   A1 run_batches: template_id / template_version / experiment_definition_version /
--      fixed_conditions_hash —— 批次级模板标识与固定条件哈希(可筛选列)
--   A2 agent_runs: config_hash / per_run_config(JSONB 完整不可变快照) /
--      template_id / experiment_definition_version —— 每次运行的配置快照
--   A3 test_jobs: template_id / template_version —— 模板化匿名/所有者任务
--
-- 口径说明:
--   - 不建立实验模板数据库表;第一版模板以版本化代码常量为单一真源
--     (engine/src/bdlh_runtime/experiments/templates.py),数据库只存标识列;
--   - 历史行全部保持 NULL(不回填、不重标 agent_mode 与历史成绩);
--   - run_batches.fixed_conditions(JSONB)继续作为完整条件载体,
--     fixed_conditions_hash 是其规范化序列化(键排序+紧凑JSON)的 SHA-256,
--     由引擎写入,数据库不做生成列;
--   - 常用筛选字段(template_id / template_version / config_hash /
--      experiment_definition_version)建索引,不做复合笛卡尔积查询。
--
-- 数据处理方式:纯增量 DDL;现有数据全部保持原状(NULL 表示"旧实验定义")。
-- 停机要求:不需要停止 Data 或 Engine 服务;建议低峰执行并先备份。
-- 幂等:DDL 使用 IF NOT EXISTS;可安全重跑。
-- 本脚本由维护者手动执行,应用启动、容器启动与测试不会自动执行迁移。

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

-- ══ A1 批次级模板标识与固定条件哈希 ══

ALTER TABLE touchstone.run_batches
    ADD COLUMN IF NOT EXISTS template_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS template_version INTEGER,
    ADD COLUMN IF NOT EXISTS experiment_definition_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS fixed_conditions_hash VARCHAR(64);

ALTER TABLE touchstone.run_batches
    DROP CONSTRAINT IF EXISTS run_batch_template_version_valid;
ALTER TABLE touchstone.run_batches
    ADD CONSTRAINT run_batch_template_version_valid CHECK (
        (template_id IS NULL AND template_version IS NULL)
        OR (template_id IS NOT NULL AND template_version IS NOT NULL AND template_version > 0)
    );

CREATE INDEX IF NOT EXISTS idx_run_batches_template
    ON touchstone.run_batches(template_id, template_version);
CREATE INDEX IF NOT EXISTS idx_run_batches_fixed_conditions_hash
    ON touchstone.run_batches(fixed_conditions_hash);

COMMENT ON COLUMN touchstone.run_batches.template_id IS
    '实验模板标识(代码常量单一真源,如 governance-on-off);NULL=2026-08-26 前的旧实验定义批次';
COMMENT ON COLUMN touchstone.run_batches.template_version IS
    '实验模板版本;与 template_id 同为 NULL 或同非 NULL';
COMMENT ON COLUMN touchstone.run_batches.experiment_definition_version IS
    '实验定义口径版本(run-config-v2);用于区分旧 agent_mode 对照与新模板单变量实验';
COMMENT ON COLUMN touchstone.run_batches.fixed_conditions_hash IS
    '批次固定条件的规范化哈希(键排序+紧凑JSON 的 SHA-256,引擎计算);变体只能改变声明的主自变量';

-- ══ A2 运行级配置快照 ══

ALTER TABLE touchstone.agent_runs
    ADD COLUMN IF NOT EXISTS config_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS per_run_config JSONB,
    ADD COLUMN IF NOT EXISTS template_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS template_version INTEGER,
    ADD COLUMN IF NOT EXISTS experiment_definition_version VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_agent_runs_config_hash
    ON touchstone.agent_runs(config_hash);
CREATE INDEX IF NOT EXISTS idx_agent_runs_template
    ON touchstone.agent_runs(template_id, template_version);

COMMENT ON COLUMN touchstone.agent_runs.config_hash IS
    '本次运行 RunConfig 规范化序列化的 SHA-256;同配置必同哈希,NULL=历史运行(旧实验定义)';
COMMENT ON COLUMN touchstone.agent_runs.per_run_config IS
    '完整不可变运行配置快照(config_version=2:执行引擎/工具提供方式/治理/上下文/限制/模型请求与生效参数/工件版本);不包含 gold';
COMMENT ON COLUMN touchstone.agent_runs.template_id IS
    '发起本运行的实验模板标识(冗余筛选列,真源在批次);NULL=历史运行';
COMMENT ON COLUMN touchstone.agent_runs.experiment_definition_version IS
    '实验定义口径版本;legacy-implementation-profile-diagnostic 表示旧 baseline/full-system 整体实现诊断';

-- ══ A3 任务级模板标识 ══

ALTER TABLE touchstone.test_jobs
    ADD COLUMN IF NOT EXISTS template_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS template_version INTEGER;

COMMENT ON COLUMN touchstone.test_jobs.template_id IS
    '匿名/所有者任务使用的实验模板标识;NULL=模板机制上线前的旧任务';
COMMENT ON COLUMN touchstone.test_jobs.template_version IS
    '实验模板版本;与 template_id 同为 NULL 或同非 NULL';

-- 压缩用例新增 native-matrix 操作口径(4×1 新默认上下文运行计划)
ALTER TABLE touchstone.test_jobs
    DROP CONSTRAINT IF EXISTS test_job_scope_valid;
ALTER TABLE touchstone.test_jobs
    ADD CONSTRAINT test_job_scope_valid CHECK (
        execution_scope IN ('comparison-full', 'context-only', 'current-combo', 'full-matrix', 'native-matrix')
    );

-- ══ 登记与核验 ══

INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260826-run-config-snapshot.sql', '运行配置快照与实验模板标识列:run_batches/agent_runs/test_jobs 增量列与索引')
ON CONFLICT DO NOTHING;

COMMIT;

-- 核验 SQL(维护者执行后手动验证,不自动运行):
--   1) 列已存在:
--      SELECT column_name FROM information_schema.columns
--      WHERE table_schema='touchstone' AND table_name='agent_runs'
--        AND column_name IN ('config_hash','per_run_config','template_id');
--   2) 索引已建:
--      SELECT indexname FROM pg_indexes
--      WHERE schemaname='touchstone' AND tablename IN ('agent_runs','run_batches')
--        AND indexname LIKE 'idx_%';
--   3) 历史行未被改动(全部为 NULL):
--      SELECT count(*) FROM touchstone.agent_runs WHERE config_hash IS NOT NULL;  -- 期望 0(执行时点)
