-- =============================================================================
-- platform_contract.sql
-- 平台 Schema 契约登记表：记录各 schema 的所有者与版本，供运维核对。
-- 执行前须已完成 bootstrap（存在 registry schema）。
-- =============================================================================

CREATE TABLE IF NOT EXISTS registry.platform_schema_contract (
    contract_key VARCHAR(96) PRIMARY KEY,
    contract_version VARCHAR(32) NOT NULL,
    owner_service VARCHAR(96) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE registry.platform_schema_contract IS '平台 Schema 契约登记：声明各业务 schema 的所有者服务与版本';
COMMENT ON COLUMN registry.platform_schema_contract.contract_key IS '契约键，通常与 schema 名一致，如 business/runtime/registry';
COMMENT ON COLUMN registry.platform_schema_contract.contract_version IS '契约版本号，如 v1';
COMMENT ON COLUMN registry.platform_schema_contract.owner_service IS '拥有该 schema 的服务名，如 bdlh-runtime-data';
COMMENT ON COLUMN registry.platform_schema_contract.created_at IS '首次登记时间';
COMMENT ON COLUMN registry.platform_schema_contract.updated_at IS '最近更新时间';

INSERT INTO registry.platform_schema_contract (contract_key, contract_version, owner_service)
VALUES
    ('business', 'v1', 'bdlh-runtime-data'),
    ('runtime', 'v1', 'bdlh-runtime-data'),
    ('registry', 'v1', 'bdlh-runtime-data')
ON CONFLICT (contract_key) DO UPDATE
SET contract_version = EXCLUDED.contract_version,
    owner_service = EXCLUDED.owner_service,
    updated_at = CURRENT_TIMESTAMP;
