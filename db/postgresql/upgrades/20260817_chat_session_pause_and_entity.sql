-- 已有库增量：ChatSession 暂停路由字段 + 受控会话实体（手工执行，非启动自动迁移）
-- 全量建库请直接使用 schema/runtime_core.sql。

ALTER TABLE runtime.chat_session
    ADD COLUMN IF NOT EXISTS pause_reason VARCHAR(32),
    ADD COLUMN IF NOT EXISTS awaiting_route_confirm BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS verified_entity_state JSONB;
