-- 20260830-context-access-grants.sql
-- 上下文工作台 P1 细粒度 RBAC:跨所有者工件读取授权表。
--
-- 内容:
--   1. 新建 touchstone.context_access_grants(所有者向被授权方授予
--      ARTIFACT_READ 权限;可选绑定单个 build_id,NULL 表示该所有者全部构建);
--   2. 活跃授权的部分唯一索引(撤销后可重新授予);
--   3. 登记 database_changes。
--
-- 现有数据处理:纯新增结构,不回填、不修改任何既有表数据。
-- 审计日志复用既有 touchstone.audit_log(account_id/action/succeeded/detail),
-- 本脚本不新建审计表。
-- 服务影响:无锁冲突风险(只建新表);Data/Engine 可在线执行。
-- 幂等性:CREATE TABLE IF NOT EXISTS + 索引 IF NOT EXISTS + 登记 ON CONFLICT DO NOTHING。

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE IF NOT EXISTS touchstone.context_access_grants (
    id                  UUID PRIMARY KEY,
    owner_account_id    UUID NOT NULL
                        REFERENCES touchstone.accounts(id) ON DELETE CASCADE,
    grantee_account_id  UUID NOT NULL
                        REFERENCES touchstone.accounts(id) ON DELETE CASCADE,
    scope               VARCHAR(40) NOT NULL DEFAULT 'ARTIFACT_READ',
    build_id            VARCHAR(200),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ,
    CONSTRAINT context_access_grant_scope_valid
        CHECK (scope IN ('ARTIFACT_READ')),
    CONSTRAINT context_access_grant_not_self
        CHECK (owner_account_id <> grantee_account_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_context_access_grants_active
    ON touchstone.context_access_grants (owner_account_id, grantee_account_id, scope, build_id)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_context_access_grants_grantee
    ON touchstone.context_access_grants (grantee_account_id)
    WHERE revoked_at IS NULL;

INSERT INTO touchstone.database_changes (script_name, description)
VALUES (
    '20260830-context-access-grants.sql',
    '上下文工作台 P1 细粒度 RBAC:新增 context_access_grants 跨所有者工件读取授权表(审计复用 audit_log)'
)
ON CONFLICT (script_name) DO NOTHING;

-- 核验:表与索引存在,登记行出现
SELECT to_regclass('touchstone.context_access_grants') AS grants_table,
       indexname AS active_index
FROM pg_indexes
WHERE schemaname = 'touchstone'
  AND tablename = 'context_access_grants'
  AND indexname = 'idx_context_access_grants_active';

SELECT script_name, applied_at
FROM touchstone.database_changes
WHERE script_name = '20260830-context-access-grants.sql';

COMMIT;
