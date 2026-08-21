-- =============================================================================
-- memory_service.sql
-- Memory Service 专用表（建议由 memory 服务账号使用）。
-- =============================================================================

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

COMMENT ON TABLE memory.consumer_inbox IS 'Memory 服务消费者 Inbox：事件去重与处理结果';
COMMENT ON COLUMN memory.consumer_inbox.consumer_group IS '消费组名';
COMMENT ON COLUMN memory.consumer_inbox.event_id IS '事件 ID';
COMMENT ON COLUMN memory.consumer_inbox.status IS '处理状态：PROCESSING/PROCESSED/FAILED';
COMMENT ON COLUMN memory.consumer_inbox.result_summary IS '处理结果摘要';
COMMENT ON COLUMN memory.consumer_inbox.last_error IS '失败原因';
COMMENT ON COLUMN memory.consumer_inbox.processed_at IS '处理完成时间';
COMMENT ON COLUMN memory.consumer_inbox.created_at IS '创建时间';
COMMENT ON COLUMN memory.consumer_inbox.updated_at IS '最近更新时间';

CREATE TABLE IF NOT EXISTS memory.deletion_audit (
    audit_id UUID PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    summary VARCHAR(1000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE memory.deletion_audit IS '记忆删除审计：用户记忆清除操作留痕';
COMMENT ON COLUMN memory.deletion_audit.audit_id IS '审计记录 ID';
COMMENT ON COLUMN memory.deletion_audit.user_id IS '被删除记忆所属用户';
COMMENT ON COLUMN memory.deletion_audit.summary IS '删除摘要说明';
COMMENT ON COLUMN memory.deletion_audit.created_at IS '记录时间';
