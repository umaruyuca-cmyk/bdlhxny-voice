-- Java 数据平面运行态核心表的全量建表脚本。

CREATE TABLE runtime.chat_session (
    user_id BIGINT NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT '新的对话',
    pending_run_id VARCHAR(64),
    pending_thread_id VARCHAR(255),
    pending_checkpoint_id VARCHAR(255),
    pending_runtime_path VARCHAR(64),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, session_id)
);

CREATE INDEX idx_runtime_chat_session_user_updated
    ON runtime.chat_session(user_id, updated_at DESC);

CREATE TABLE runtime.chat_message (
    message_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_runtime_chat_message_session
        FOREIGN KEY (user_id, session_id)
        REFERENCES runtime.chat_session(user_id, session_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_runtime_chat_message_session
    ON runtime.chat_message(user_id, session_id, message_id);

CREATE TABLE runtime.run_registry (
    run_id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    checkpoint_id VARCHAR(255),
    runtime_path VARCHAR(64) NOT NULL DEFAULT 'legacy_root_graph',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runtime_run_registry_user_updated
    ON runtime.run_registry(user_id, updated_at DESC);

CREATE INDEX idx_runtime_run_registry_thread
    ON runtime.run_registry(thread_id);

CREATE TABLE runtime.analysis_history (
    history_id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    run_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (
        status IN ('SUCCESS', 'PARTIAL', 'LIMITED', 'FAILED', 'RUNNING')
    ),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runtime_analysis_history_thread_user_created
    ON runtime.analysis_history(thread_id, user_id, created_at, history_id);

CREATE INDEX idx_runtime_analysis_history_run
    ON runtime.analysis_history(run_id);
