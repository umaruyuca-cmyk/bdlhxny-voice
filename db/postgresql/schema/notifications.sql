-- =============================================================================
-- notifications.sql
-- 用户通知投影（由通知消费者写入；Inbox 仍在 runtime.consumer_inbox）。
-- =============================================================================

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

COMMENT ON TABLE runtime.user_notification IS '用户通知投影：任务触发后的可读通知记录';
COMMENT ON COLUMN runtime.user_notification.notification_id IS '通知 ID';
COMMENT ON COLUMN runtime.user_notification.event_id IS '来源 Outbox/消息事件 ID（唯一）';
COMMENT ON COLUMN runtime.user_notification.user_id IS '接收用户 ID';
COMMENT ON COLUMN runtime.user_notification.task_id IS '关联持续任务 ID';
COMMENT ON COLUMN runtime.user_notification.channel IS '通知渠道，如 IN_APP / PUSH';
COMMENT ON COLUMN runtime.user_notification.title IS '通知标题';
COMMENT ON COLUMN runtime.user_notification.body IS '通知正文';
COMMENT ON COLUMN runtime.user_notification.observed_price IS '观测到的价格（可选）';
COMMENT ON COLUMN runtime.user_notification.currency IS '价格币种（可选）';
COMMENT ON COLUMN runtime.user_notification.observation_time IS '观测时间（可选）';
COMMENT ON COLUMN runtime.user_notification.created_at IS '创建时间';
