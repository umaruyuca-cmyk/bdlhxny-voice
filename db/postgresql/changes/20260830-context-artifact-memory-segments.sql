-- 20260830: 工件 Segment 明细快照字段(增量脚本)
-- 背景:20260830-context-memory-workbench.sql 建立的 context_artifacts 只保存
-- 消息序列/哈希/token,Engine 工件中的 memory_segments 明细(轮次范围、source
-- hash 短值、状态、生成方式、token、是否命中缓存、安全摘要正文)在
-- CONTEXT_BUILD_STORE=data-service 下重读丢失,页面"历史摘要复用"区域为空。
-- 本脚本补充显式 JSONB 字段;不回填历史(该表尚无数据,DEFAULT '[]' 即可)。
-- Data/Engine 可在线执行,ALTER 仅短锁表。失败整体回滚。

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE touchstone.context_artifacts
    ADD COLUMN IF NOT EXISTS memory_segments JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'context_artifact_memory_segments_array'
          AND conrelid = 'touchstone.context_artifacts'::regclass
    ) THEN
        ALTER TABLE touchstone.context_artifacts
            ADD CONSTRAINT context_artifact_memory_segments_array
            CHECK (jsonb_typeof(memory_segments) = 'array');
    END IF;
END $$;

COMMENT ON COLUMN touchstone.context_artifacts.memory_segments IS
    '构建工件的历史轮 Segment 明细快照(展示与追溯用;事实真源仍是 context_memory_segments 表)';

INSERT INTO touchstone.database_changes (script_name, description)
VALUES (
    '20260830-context-artifact-memory-segments.sql',
    'context_artifacts 增加工件 Segment 明细快照字段'
)
ON CONFLICT (script_name) DO NOTHING;

COMMIT;

-- 执行后核验：
-- SELECT script_name, applied_at FROM touchstone.database_changes
-- WHERE script_name = '20260830-context-artifact-memory-segments.sql';
-- SELECT column_name, data_type, column_default FROM information_schema.columns
-- WHERE table_schema='touchstone' AND table_name='context_artifacts' AND column_name='memory_segments';
