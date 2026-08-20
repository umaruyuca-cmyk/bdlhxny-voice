-- Cognitive 运行投影和事件的全量建表脚本，由 Java 数据平面所有。

CREATE TABLE runtime.run_projection (
    run_id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    next_stage VARCHAR(128),
    final_response JSONB,
    interrupts JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runtime_run_projection_user_updated
    ON runtime.run_projection(user_id, updated_at DESC);

CREATE TABLE runtime.run_event (
    run_id VARCHAR(64) NOT NULL REFERENCES runtime.run_projection(run_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL CHECK (sequence_no >= 0),
    event_type VARCHAR(96) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, sequence_no)
);
