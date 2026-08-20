-- Java 通知消费者投影表的全量建表脚本；消费者 Inbox 仍归 runtime Schema 所有。

CREATE TABLE runtime.user_notification (
    notification_id UUID PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    user_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(64) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    body TEXT NOT NULL,
    observed_price NUMERIC(20, 6),
    currency VARCHAR(8),
    observation_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runtime_user_notification_user_created
    ON runtime.user_notification(user_id, created_at DESC);
