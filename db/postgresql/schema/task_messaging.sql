-- =============================================================================
-- task_messaging.sql
-- 持续任务、事务 Outbox、本地消费者 Inbox（Java Data Plane）。
-- =============================================================================

-- ---------------------------------------------------------------------------
-- financial_task：金融持续任务（如价格条件观察）
-- ---------------------------------------------------------------------------
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

COMMENT ON TABLE runtime.financial_task IS '金融持续任务：调度唤醒、过期与任务载荷';
COMMENT ON COLUMN runtime.financial_task.task_id IS '任务 ID';
COMMENT ON COLUMN runtime.financial_task.user_id IS '用户 ID（字符串形态，兼容服务间传递）';
COMMENT ON COLUMN runtime.financial_task.status IS '任务状态：DRAFT/SCHEDULED/RUNNING/WAITING/TRIGGERED/COMPLETED/FAILED/CANCELLED/EXPIRED';
COMMENT ON COLUMN runtime.financial_task.version IS '乐观锁版本号';
COMMENT ON COLUMN runtime.financial_task.next_wakeup_at IS '下次唤醒时间';
COMMENT ON COLUMN runtime.financial_task.expires_at IS '任务过期时间';
COMMENT ON COLUMN runtime.financial_task.payload IS '任务定义与上下文 JSON';
COMMENT ON COLUMN runtime.financial_task.notification_event_id IS '关联已发出的通知 Outbox 事件 ID';
COMMENT ON COLUMN runtime.financial_task.created_at IS '创建时间';
COMMENT ON COLUMN runtime.financial_task.updated_at IS '最近更新时间';

-- ---------------------------------------------------------------------------
-- outbox_event：可靠投递 Outbox（写库事务后异步发布到 MQ）
-- ---------------------------------------------------------------------------
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

COMMENT ON TABLE runtime.outbox_event IS '事务 Outbox：业务提交后异步可靠发布到消息中间件';
COMMENT ON COLUMN runtime.outbox_event.event_id IS '事件 UUID';
COMMENT ON COLUMN runtime.outbox_event.topic IS '目标 Topic';
COMMENT ON COLUMN runtime.outbox_event.event_type IS '事件类型名';
COMMENT ON COLUMN runtime.outbox_event.schema_version IS '事件载荷 schema 版本';
COMMENT ON COLUMN runtime.outbox_event.aggregate_type IS '聚合根类型';
COMMENT ON COLUMN runtime.outbox_event.aggregate_id IS '聚合根 ID';
COMMENT ON COLUMN runtime.outbox_event.aggregate_version IS '聚合版本';
COMMENT ON COLUMN runtime.outbox_event.idempotency_key IS '发布幂等键（全局唯一）';
COMMENT ON COLUMN runtime.outbox_event.authenticated_user_id IS '触发用户 ID（可空，系统事件）';
COMMENT ON COLUMN runtime.outbox_event.status IS '发布状态：PENDING/PUBLISHING/PUBLISHED/FAILED';
COMMENT ON COLUMN runtime.outbox_event.attempts IS '已尝试发布次数';
COMMENT ON COLUMN runtime.outbox_event.max_attempts IS '最大尝试次数';
COMMENT ON COLUMN runtime.outbox_event.next_attempt_at IS '下次可尝试时间';
COMMENT ON COLUMN runtime.outbox_event.claim_token IS 'Relay 认领令牌';
COMMENT ON COLUMN runtime.outbox_event.claimed_at IS '认领时间';
COMMENT ON COLUMN runtime.outbox_event.payload IS '事件载荷 JSON';
COMMENT ON COLUMN runtime.outbox_event.trace_id IS '分布式追踪 ID';
COMMENT ON COLUMN runtime.outbox_event.correlation_id IS '业务关联 ID';
COMMENT ON COLUMN runtime.outbox_event.last_error IS '最近一次失败原因';
COMMENT ON COLUMN runtime.outbox_event.compensation_required IS '是否需要补偿处理';
COMMENT ON COLUMN runtime.outbox_event.created_at IS '创建时间';
COMMENT ON COLUMN runtime.outbox_event.published_at IS '成功发布时间';
COMMENT ON COLUMN runtime.outbox_event.updated_at IS '最近更新时间';

-- ---------------------------------------------------------------------------
-- consumer_inbox：本服务消费去重 / 处理结果
-- ---------------------------------------------------------------------------
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

COMMENT ON TABLE runtime.consumer_inbox IS '运行时消费者 Inbox：按消费组对事件去重并记录处理结果';
COMMENT ON COLUMN runtime.consumer_inbox.consumer_group IS '消费组名';
COMMENT ON COLUMN runtime.consumer_inbox.event_id IS '已消费事件 ID';
COMMENT ON COLUMN runtime.consumer_inbox.status IS '处理状态：PROCESSING/PROCESSED/FAILED';
COMMENT ON COLUMN runtime.consumer_inbox.result_summary IS '处理结果摘要';
COMMENT ON COLUMN runtime.consumer_inbox.last_error IS '失败原因';
COMMENT ON COLUMN runtime.consumer_inbox.processed_at IS '处理完成时间';
COMMENT ON COLUMN runtime.consumer_inbox.created_at IS '创建时间';
COMMENT ON COLUMN runtime.consumer_inbox.updated_at IS '最近更新时间';
