-- 20260830-context-access-grants-nulls-unique.sql
-- 修正 20260830-context-access-grants.sql 的活跃授权唯一索引:
-- build_id 为 NULL(表示"该所有者全部构建")时,PostgreSQL 默认唯一索引把
-- NULL 视为互异,同一 (owner, grantee, scope) 的重复全局授权不会被拒绝。
--
-- 处理:改用 NULLS NOT DISTINCT 重建部分唯一索引(PG 15+ 语法,本库为 PG 18)。
-- 现有数据:回滚式冒烟确认库内 0 行授权,无重复需要清理;若有历史库
-- 已产生重复活跃行,需先人工合并(保留最新一行,撤销其余)再执行本脚本。
-- 服务影响:仅索引重建,Data/Engine 可在线;锁等待 10s。
-- 幂等性:索引名固定,重复执行结果一致;登记 ON CONFLICT DO NOTHING。

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

DROP INDEX IF EXISTS touchstone.idx_context_access_grants_active;

CREATE UNIQUE INDEX idx_context_access_grants_active
    ON touchstone.context_access_grants (owner_account_id, grantee_account_id, scope, build_id)
    NULLS NOT DISTINCT
    WHERE revoked_at IS NULL;

INSERT INTO touchstone.database_changes (script_name, description)
VALUES (
    '20260830-context-access-grants-nulls-unique.sql',
    '修正 context_access_grants 活跃授权唯一索引:NULLS NOT DISTINCT,拒绝重复的全局(build_id 为空)授权'
)
ON CONFLICT (script_name) DO NOTHING;

-- 核验
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'touchstone'
  AND tablename = 'context_access_grants'
  AND indexname = 'idx_context_access_grants_active';

SELECT script_name, applied_at
FROM touchstone.database_changes
WHERE script_name = '20260830-context-access-grants-nulls-unique.sql';

COMMIT;
