-- 20260830: 构建表 Agent 运行快照字段(增量脚本,P1)
-- 背景:需求文档 §23 P1 要求"运行一次 Agent"、build 与唯一 run 关联、
-- 工件有效性校验和压缩/Agent 分项计量。运行结果(run_id/状态/输出/用量/
-- 发送内容哈希)需要一个显式快照字段;不写入 agent_runs 实验运行表
-- (那是固定实验轨道的生命周期),也不改动 run_id 既有语义。
-- Data/Engine 可在线执行,ALTER 仅短锁表。失败整体回滚。

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE touchstone.context_builds
    ADD COLUMN IF NOT EXISTS agent_run_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN touchstone.context_builds.agent_run_snapshot IS
    '一次构建至多一条的 Agent 运行快照:run_id/状态/输出/模型/用量/发送内容哈希;一次点击一次运行';

INSERT INTO touchstone.database_changes (script_name, description)
VALUES (
    '20260830-context-build-agent-run.sql',
    'context_builds 增加 Agent 运行快照字段(P1 单次运行与分项计量)'
)
ON CONFLICT (script_name) DO NOTHING;

COMMIT;

-- 执行后核验：
-- SELECT script_name FROM touchstone.database_changes
-- WHERE script_name = '20260830-context-build-agent-run.sql';
-- SELECT column_name, data_type, column_default FROM information_schema.columns
-- WHERE table_schema='touchstone' AND table_name='context_builds' AND column_name='agent_run_snapshot';
