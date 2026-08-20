-- PLATFORM-P1: Java Data Plane Flyway baseline.
-- The operational bootstrap creates schemas and assigns their owners before this
-- migration runs. This service must never create or migrate checkpoint/memory.

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
