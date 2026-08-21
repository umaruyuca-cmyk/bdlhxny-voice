-- =============================================================================
-- run_projection.sql
-- Cognitive 运行投影与有序事件流（Java Data Plane）。
-- =============================================================================

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

COMMENT ON TABLE runtime.run_projection IS 'Run 投影：对外可查询的运行状态摘要';
COMMENT ON COLUMN runtime.run_projection.run_id IS '运行 ID';
COMMENT ON COLUMN runtime.run_projection.user_id IS '用户 ID';
COMMENT ON COLUMN runtime.run_projection.thread_id IS '线程 ID';
COMMENT ON COLUMN runtime.run_projection.status IS '运行状态（编排侧状态字面量）';
COMMENT ON COLUMN runtime.run_projection.next_stage IS '下一阶段/节点提示（可空）';
COMMENT ON COLUMN runtime.run_projection.final_response IS '最终对外响应 JSON（可空，运行中为空）';
COMMENT ON COLUMN runtime.run_projection.interrupts IS '中断/待办列表 JSON 数组';
COMMENT ON COLUMN runtime.run_projection.updated_at IS '最近更新时间';

CREATE TABLE runtime.run_event (
    run_id VARCHAR(64) NOT NULL REFERENCES runtime.run_projection(run_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL CHECK (sequence_no >= 0),
    event_type VARCHAR(96) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, sequence_no)
);

COMMENT ON TABLE runtime.run_event IS 'Run 事件流：按 sequence_no 有序追加的可回放事件';
COMMENT ON COLUMN runtime.run_event.run_id IS '所属运行 ID';
COMMENT ON COLUMN runtime.run_event.sequence_no IS '事件序号（同一 run 内从 0 递增）';
COMMENT ON COLUMN runtime.run_event.event_type IS '事件类型名（与 SSE/契约对齐）';
COMMENT ON COLUMN runtime.run_event.payload IS '事件载荷 JSON';
COMMENT ON COLUMN runtime.run_event.created_at IS '写入时间';
