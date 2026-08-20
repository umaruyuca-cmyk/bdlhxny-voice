-- PLATFORM-P3: Java-owned task completion, transactional outbox and local consumer inbox.

CREATE TABLE runtime.financial_task (
    task_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (
        status IN ('DRAFT', 'SCHEDULED', 'RUNNING', 'WAITING', 'TRIGGERED',
                   'COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED')
    ),
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    next_wakeup_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    notification_event_id UUID UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runtime_financial_task_user_updated
    ON runtime.financial_task(user_id, updated_at DESC);

CREATE INDEX idx_runtime_financial_task_due
    ON runtime.financial_task(status, next_wakeup_at)
    WHERE status IN ('SCHEDULED', 'WAITING');

CREATE TABLE runtime.outbox_event (
    event_id UUID PRIMARY KEY,
    topic VARCHAR(160) NOT NULL,
    event_type VARCHAR(120) NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    aggregate_type VARCHAR(80) NOT NULL,
    aggregate_id VARCHAR(128) NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK (aggregate_version >= 0),
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    authenticated_user_id VARCHAR(128),
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'PUBLISHING', 'PUBLISHED', 'FAILED')
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 8 CHECK (max_attempts >= 1),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claim_token UUID,
    claimed_at TIMESTAMPTZ,
    payload JSONB NOT NULL,
    trace_id VARCHAR(128),
    correlation_id VARCHAR(128),
    last_error VARCHAR(1000),
    compensation_required BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runtime_outbox_claim
    ON runtime.outbox_event(status, next_attempt_at, created_at)
    WHERE status IN ('PENDING', 'PUBLISHING');

CREATE INDEX idx_runtime_outbox_aggregate
    ON runtime.outbox_event(aggregate_type, aggregate_id, created_at);

CREATE TABLE runtime.consumer_inbox (
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

CREATE INDEX idx_runtime_consumer_inbox_status
    ON runtime.consumer_inbox(consumer_group, status, updated_at);
