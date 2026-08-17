-- M6: one real persistent financial observation task and an idempotent notification outbox.
-- Python Runtime owns these tables. Apply this migration before enabling the worker in production.

CREATE TABLE IF NOT EXISTS public.bdlh_runtime_financial_task (
    task_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (
        status IN (
            'DRAFT', 'SCHEDULED', 'RUNNING', 'WAITING', 'TRIGGERED',
            'COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED'
        )
    ),
    next_wakeup_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_financial_task_due
    ON public.bdlh_runtime_financial_task(status, next_wakeup_at)
    WHERE status IN ('SCHEDULED', 'WAITING');

CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_financial_task_user
    ON public.bdlh_runtime_financial_task(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.bdlh_runtime_task_wakeup (
    wakeup_key VARCHAR(320) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES public.bdlh_runtime_financial_task(task_id),
    scheduled_for TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_task_wakeup_task
    ON public.bdlh_runtime_task_wakeup(task_id, scheduled_for DESC);

CREATE TABLE IF NOT EXISTS public.bdlh_runtime_notification_outbox (
    outbox_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES public.bdlh_runtime_financial_task(task_id),
    user_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(384) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL CHECK (status IN ('PENDING', 'SENDING', 'SENT', 'FAILED')),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_notification_pending
    ON public.bdlh_runtime_notification_outbox(status, created_at)
    WHERE status IN ('PENDING', 'FAILED');

CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_notification_user
    ON public.bdlh_runtime_notification_outbox(user_id, updated_at DESC);
