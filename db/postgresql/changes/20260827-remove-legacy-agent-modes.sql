-- 删除已经停用的多 Agent 实现目录，只保留统一原生 Tool Calling 的运行记录。
--
-- 数据处理方式：
--   1. 旧批次的 AGENT_IMPLEMENTATION 自变量置空；
--   2. 删除 agent_runs 上未被当前服务使用的实现版本外键列；
--   3. 删除旧 Agent 实现及版本目录表；
--   4. 收紧实验任务范围与上下文自变量约束。
-- 执行前请备份。DDL 会短暂锁表，建议在低峰期执行；应用无需长期停机。

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '2min';

UPDATE touchstone.run_batches
SET experiment_variable = NULL
WHERE experiment_variable = 'AGENT_IMPLEMENTATION';

ALTER TABLE touchstone.run_batches
    DROP CONSTRAINT IF EXISTS run_batch_experiment_variable_valid;
ALTER TABLE touchstone.run_batches
    ADD CONSTRAINT run_batch_experiment_variable_valid CHECK (
        experiment_variable IS NULL
        OR experiment_variable = 'CONTEXT_STRATEGY'
    );

ALTER TABLE touchstone.agent_runs
    DROP CONSTRAINT IF EXISTS agent_run_agent_version_fk,
    DROP CONSTRAINT IF EXISTS agent_run_agent_pair_valid,
    DROP COLUMN IF EXISTS agent_id,
    DROP COLUMN IF EXISTS agent_version;

DROP TABLE IF EXISTS touchstone.agent_versions;
DROP TABLE IF EXISTS touchstone.agent_implementations;

ALTER TABLE touchstone.test_jobs
    DROP CONSTRAINT IF EXISTS test_job_scope_valid;
ALTER TABLE touchstone.test_jobs
    ADD CONSTRAINT test_job_scope_valid CHECK (
        execution_scope IN ('context-only', 'current-combo', 'native-matrix', 'template-batch')
    );  -- 修正: 原稿误含 actual_agent_steps 检查(该列属 agent_runs), 此处仅校验 scope

UPDATE touchstone.database_changes
SET script_name = '03-create-experiment-trace-tables.sql',
    description = '创建实验追溯、调用明细、指标和发布记录表'
WHERE script_name = '03-create-agent-comparison-tables.sql'
  AND NOT EXISTS (
      SELECT 1 FROM touchstone.database_changes
      WHERE script_name = '03-create-experiment-trace-tables.sql'
  );

UPDATE touchstone.database_changes
SET script_name = '04-seed-context-catalog.sql',
    description = '写入四种上下文策略'
WHERE script_name = '04-seed-agent-and-context-catalog.sql'
  AND NOT EXISTS (
      SELECT 1 FROM touchstone.database_changes
      WHERE script_name = '04-seed-context-catalog.sql'
  );

INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260827-remove-legacy-agent-modes.sql', '删除旧 Agent 实现目录、版本外键和多实现实验约束')
ON CONFLICT (script_name) DO NOTHING;

COMMIT;

-- 核验：以下查询应返回 0 行。
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'touchstone'
--   AND table_name IN ('agent_implementations', 'agent_versions');
