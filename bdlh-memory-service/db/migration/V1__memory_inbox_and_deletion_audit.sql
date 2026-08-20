-- Owned and executed only by bdlh-memory-service using bdlh_memory_service role.
CREATE TABLE IF NOT EXISTS memory.consumer_inbox (
    consumer_group VARCHAR(160) NOT NULL,
    event_id UUID NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('PROCESSING', 'PROCESSED', 'FAILED')),
    result_summary VARCHAR(1000),
    last_error VARCHAR(1000),
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (consumer_group, event_id)
);

CREATE TABLE IF NOT EXISTS memory.deletion_audit (
    audit_id UUID PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    summary VARCHAR(1000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
