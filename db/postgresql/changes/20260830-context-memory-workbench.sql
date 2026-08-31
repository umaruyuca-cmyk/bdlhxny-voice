-- 20260830: 上下文压缩工作台 P0 持久化结构
-- 执行要求:先备份；建议低峰期执行；Data/Engine 可在线，但 ALTER context_builds
-- 会短暂取表锁。失败整体回滚。本脚本只建结构，不导入冻结 Session JSON。

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE IF NOT EXISTS touchstone.context_sessions (
    id                  VARCHAR(200) PRIMARY KEY,
    account_id          UUID NOT NULL REFERENCES touchstone.accounts(id) ON DELETE CASCADE,
    title               VARCHAR(500) NOT NULL,
    source_type         VARCHAR(30) NOT NULL DEFAULT 'PRODUCTION_DB',
    source_ref          TEXT,
    source_hash         VARCHAR(100) NOT NULL,
    source_version      BIGINT NOT NULL DEFAULT 1,
    status              VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT context_session_source_type_valid
        CHECK (source_type IN ('PRODUCTION_DB', 'FROZEN_FILE')),
    CONSTRAINT context_session_status_valid
        CHECK (status IN ('ACTIVE', 'ARCHIVED', 'INVALIDATED')),
    CONSTRAINT context_session_source_version_valid CHECK (source_version > 0)
);

CREATE TABLE IF NOT EXISTS touchstone.session_events (
    session_id          VARCHAR(200) NOT NULL
                        REFERENCES touchstone.context_sessions(id) ON DELETE CASCADE,
    event_id            VARCHAR(200) NOT NULL,
    account_id          UUID NOT NULL REFERENCES touchstone.accounts(id) ON DELETE CASCADE,
    turn_id             VARCHAR(100) NOT NULL,
    sequence            INTEGER NOT NULL,
    event_type          VARCHAR(50) NOT NULL,
    role                VARCHAR(30) NOT NULL,
    content             TEXT,
    content_ref         TEXT,
    token_count         INTEGER NOT NULL DEFAULT 0,
    occurred_at         TIMESTAMPTZ NOT NULL,
    tool_call_id        VARCHAR(200),
    parent_event_id     VARCHAR(200),
    security_level      VARCHAR(30) NOT NULL DEFAULT 'OWNER',
    content_hash        VARCHAR(100) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, event_id),
    UNIQUE (session_id, sequence),
    CONSTRAINT session_event_type_valid
        CHECK (event_type IN ('user_message', 'assistant_message', 'tool_call', 'tool_result', 'system_event')),
    CONSTRAINT session_event_security_valid
        CHECK (security_level IN ('OWNER', 'REDACTED', 'REFERENCE_ONLY')),
    CONSTRAINT session_event_content_present
        CHECK (content IS NOT NULL OR content_ref IS NOT NULL),
    CONSTRAINT session_event_token_count_valid CHECK (token_count >= 0),
    CONSTRAINT session_event_sequence_valid CHECK (sequence > 0)
);

CREATE TABLE IF NOT EXISTS touchstone.context_memory_segments (
    id                  UUID PRIMARY KEY,
    session_id          VARCHAR(200) NOT NULL
                        REFERENCES touchstone.context_sessions(id) ON DELETE CASCADE,
    account_id          UUID NOT NULL REFERENCES touchstone.accounts(id) ON DELETE CASCADE,
    start_event_id      VARCHAR(200) NOT NULL,
    end_event_id        VARCHAR(200) NOT NULL,
    source_event_ids    JSONB NOT NULL,
    source_hash         VARCHAR(100) NOT NULL,
    source_tokens       INTEGER NOT NULL,
    summary_content     TEXT NOT NULL,
    summary_tokens      INTEGER NOT NULL,
    status              VARCHAR(30) NOT NULL,
    summary_model       VARCHAR(200),
    prompt_version      VARCHAR(100) NOT NULL,
    algorithm_version   VARCHAR(100) NOT NULL,
    generation_mode     VARCHAR(30) NOT NULL,
    fallback_reason     VARCHAR(100),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    frozen_at           TIMESTAMPTZ,
    superseded_by       UUID REFERENCES touchstone.context_memory_segments(id),
    CONSTRAINT memory_segment_source_ids_array
        CHECK (jsonb_typeof(source_event_ids) = 'array'),
    CONSTRAINT memory_segment_status_valid
        CHECK (status IN ('DRAFT', 'VALIDATED', 'FROZEN', 'SUPERSEDED', 'INVALIDATED')),
    CONSTRAINT memory_segment_generation_valid
        CHECK (generation_mode IN ('LLM', 'EXTRACTIVE_FALLBACK')),
    CONSTRAINT memory_segment_tokens_valid
        CHECK (source_tokens >= 0 AND summary_tokens >= 0)
);

-- 既有 context_builds 继续服务运行审计；补充“先构建、后运行”的生产字段。
ALTER TABLE touchstone.context_builds
    ALTER COLUMN run_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS session_id VARCHAR(200)
        REFERENCES touchstone.context_sessions(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS account_id UUID
        REFERENCES touchstone.accounts(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS current_request_event_id VARCHAR(200),
    ADD COLUMN IF NOT EXISTS algorithm_version VARCHAR(100),
    ADD COLUMN IF NOT EXISTS config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_version BIGINT,
    ADD COLUMN IF NOT EXISTS current_phase VARCHAR(50),
    ADD COLUMN IF NOT EXISTS step_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS budget_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS item_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS llm_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128),
    ADD COLUMN IF NOT EXISTS request_hash VARCHAR(100),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'context_build_has_source'
          AND conrelid = 'touchstone.context_builds'::regclass
    ) THEN
        ALTER TABLE touchstone.context_builds
            ADD CONSTRAINT context_build_has_source
            CHECK (run_id IS NOT NULL OR session_id IS NOT NULL) NOT VALID;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS touchstone.context_artifacts (
    id                  UUID PRIMARY KEY,
    context_build_id    UUID NOT NULL UNIQUE
                        REFERENCES touchstone.context_builds(id) ON DELETE CASCADE,
    account_id          UUID NOT NULL REFERENCES touchstone.accounts(id) ON DELETE CASCADE,
    message_sequence    JSONB NOT NULL,
    content_hash        VARCHAR(100) NOT NULL,
    token_count         INTEGER NOT NULL,
    tokenizer_version   VARCHAR(100) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalidated_at      TIMESTAMPTZ,
    invalidation_reason VARCHAR(100),
    CONSTRAINT context_artifact_messages_array
        CHECK (jsonb_typeof(message_sequence) = 'array'),
    CONSTRAINT context_artifact_token_count_valid CHECK (token_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_context_sessions_account_updated
    ON touchstone.context_sessions(account_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_events_turn
    ON touchstone.session_events(session_id, turn_id, sequence);
CREATE INDEX IF NOT EXISTS idx_memory_segments_session_status
    ON touchstone.context_memory_segments(session_id, status, frozen_at DESC);
CREATE INDEX IF NOT EXISTS idx_context_builds_session_created
    ON touchstone.context_builds(session_id, created_at DESC)
    WHERE session_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_context_build_active_session
    ON touchstone.context_builds(account_id, session_id)
    WHERE session_id IS NOT NULL AND status IN ('PENDING', 'RUNNING');
CREATE UNIQUE INDEX IF NOT EXISTS uq_context_build_owner_idempotency
    ON touchstone.context_builds(account_id, idempotency_key)
    WHERE account_id IS NOT NULL AND idempotency_key IS NOT NULL;

COMMENT ON TABLE touchstone.context_sessions IS
    '生产上下文会话事实入口；固定实验 JSON 默认不导入，只通过 FROZEN_FILE 适配器读取';
COMMENT ON TABLE touchstone.session_events IS
    '只追加的原始会话事件；user_message 开启 turn，后续助手/工具事件归入同一 turn';
COMMENT ON TABLE touchstone.context_memory_segments IS
    '跨构建复用的冻结历史摘要；原始事件仍为事实真源';
COMMENT ON TABLE touchstone.context_artifacts IS
    '上下文工作台冻结的目标 API message 序列；P0 不直接运行 Agent';

INSERT INTO touchstone.database_changes (script_name, description)
VALUES (
    '20260830-context-memory-workbench.sql',
    '新增生产会话事件、增量摘要、独立上下文构建与冻结工件结构'
)
ON CONFLICT (script_name) DO NOTHING;

COMMIT;

-- 执行后核验：
-- SELECT script_name, applied_at FROM touchstone.database_changes
-- WHERE script_name = '20260830-context-memory-workbench.sql';
-- SELECT indexname FROM pg_indexes WHERE schemaname='touchstone'
-- AND indexname IN ('uq_context_build_active_session','uq_context_build_owner_idempotency');
