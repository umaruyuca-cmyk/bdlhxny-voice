-- 平台 Schema 契约全量建表脚本：由数据库管理员手工执行，不由 Java 服务启动时执行。
-- 在执行本文件前，必须先由数据库管理员创建 Schema 并分配所属角色。
-- Java 数据平面不得创建或修改 checkpoint、memory Schema。

CREATE TABLE IF NOT EXISTS registry.platform_schema_contract (
    contract_key VARCHAR(96) PRIMARY KEY,
    contract_version VARCHAR(32) NOT NULL,
    owner_service VARCHAR(96) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO registry.platform_schema_contract (contract_key, contract_version, owner_service)
VALUES
    ('business', 'v1', 'bdlh-runtime-data'),
    ('runtime', 'v1', 'bdlh-runtime-data'),
    ('registry', 'v1', 'bdlh-runtime-data')
ON CONFLICT (contract_key) DO UPDATE
SET contract_version = EXCLUDED.contract_version,
    owner_service = EXCLUDED.owner_service,
    updated_at = CURRENT_TIMESTAMP;
