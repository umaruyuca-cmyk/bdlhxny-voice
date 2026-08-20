-- ADR-014：ChatSession pending 投影补充 pause_reason / awaiting_route_confirm
ALTER TABLE runtime.chat_session
    ADD COLUMN IF NOT EXISTS pause_reason VARCHAR(32),
    ADD COLUMN IF NOT EXISTS awaiting_route_confirm BOOLEAN NOT NULL DEFAULT FALSE;
