-- =============================================================================
-- runtime_core.sql
-- Java Data Plane 运行态核心：会话、消息、Run 索引、分析历史。
-- =============================================================================

-- ---------------------------------------------------------------------------
-- chat_session：用户会话及暂停/待续跑元数据
-- ---------------------------------------------------------------------------
CREATE TABLE runtime.chat_session (
    user_id BIGINT NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT '新的对话',
    pending_run_id VARCHAR(64),
    pending_thread_id VARCHAR(255),
    pending_checkpoint_id VARCHAR(255),
    pending_runtime_path VARCHAR(64),
    pause_reason VARCHAR(32),
    awaiting_route_confirm BOOLEAN NOT NULL DEFAULT FALSE,
    verified_entity_state JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, session_id)
);

CREATE INDEX idx_runtime_chat_session_user_updated
    ON runtime.chat_session(user_id, updated_at DESC);

COMMENT ON TABLE runtime.chat_session IS '聊天会话：标题、待续跑指针、暂停原因、受控实体快照';
COMMENT ON COLUMN runtime.chat_session.user_id IS '用户 ID（与认证体系一致的数字 ID）';
COMMENT ON COLUMN runtime.chat_session.session_id IS '会话 ID';
COMMENT ON COLUMN runtime.chat_session.title IS '会话标题';
COMMENT ON COLUMN runtime.chat_session.pending_run_id IS '待续跑的 run_id；空表示无挂起运行';
COMMENT ON COLUMN runtime.chat_session.pending_thread_id IS '待续跑线程 ID（编排侧 thread）';
COMMENT ON COLUMN runtime.chat_session.pending_checkpoint_id IS '待续跑 checkpoint_id；真断点续跑依赖非空值（ADR-014）';
COMMENT ON COLUMN runtime.chat_session.pending_runtime_path IS '待续跑运行路径，当前产品为 cognitive_finance';
COMMENT ON COLUMN runtime.chat_session.pause_reason IS '暂停原因码，如 USER_ABORT / SYSTEM_BUDGET 等';
COMMENT ON COLUMN runtime.chat_session.awaiting_route_confirm IS '是否等待用户确认 Turn Router（ask_which）';
COMMENT ON COLUMN runtime.chat_session.verified_entity_state IS '受控会话实体 JSON（如已验证标的），非 L0 checkpoint';
COMMENT ON COLUMN runtime.chat_session.updated_at IS '最近更新时间';

-- ---------------------------------------------------------------------------
-- chat_message：会话消息流水
-- ---------------------------------------------------------------------------
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

COMMENT ON TABLE runtime.chat_message IS '会话消息流水（用户/助手等）';
COMMENT ON COLUMN runtime.chat_message.message_id IS '消息自增主键';
COMMENT ON COLUMN runtime.chat_message.user_id IS '用户 ID';
COMMENT ON COLUMN runtime.chat_message.session_id IS '所属会话 ID';
COMMENT ON COLUMN runtime.chat_message.role IS '角色：user / assistant / system 等';
COMMENT ON COLUMN runtime.chat_message.content IS '消息正文';
COMMENT ON COLUMN runtime.chat_message.created_at IS '创建时间';

-- ---------------------------------------------------------------------------
-- run_registry：Run 位置索引（thread / checkpoint / 路径）
-- ---------------------------------------------------------------------------
CREATE TABLE runtime.run_registry (
    run_id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    checkpoint_id VARCHAR(255),
    runtime_path VARCHAR(64) NOT NULL DEFAULT 'cognitive_finance',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runtime_run_registry_user_updated
    ON runtime.run_registry(user_id, updated_at DESC);

CREATE INDEX idx_runtime_run_registry_thread
    ON runtime.run_registry(thread_id);

COMMENT ON TABLE runtime.run_registry IS 'Run 位置注册表：把 run_id 映射到 thread/checkpoint/运行路径';
COMMENT ON COLUMN runtime.run_registry.run_id IS '运行 ID';
COMMENT ON COLUMN runtime.run_registry.user_id IS '所属用户 ID';
COMMENT ON COLUMN runtime.run_registry.thread_id IS '编排线程 ID';
COMMENT ON COLUMN runtime.run_registry.checkpoint_id IS '最近已知 checkpoint；可为空';
COMMENT ON COLUMN runtime.run_registry.runtime_path IS '运行路径标识，默认 cognitive_finance';
COMMENT ON COLUMN runtime.run_registry.updated_at IS '最近更新时间';

-- ---------------------------------------------------------------------------
-- analysis_history：可对外展示的分析历史载荷
-- ---------------------------------------------------------------------------
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

COMMENT ON TABLE runtime.analysis_history IS '分析历史：按 run/thread 保存可展示结果载荷';
COMMENT ON COLUMN runtime.analysis_history.history_id IS '历史记录 ID';
COMMENT ON COLUMN runtime.analysis_history.user_id IS '用户 ID';
COMMENT ON COLUMN runtime.analysis_history.thread_id IS '线程 ID';
COMMENT ON COLUMN runtime.analysis_history.run_id IS '关联 run_id';
COMMENT ON COLUMN runtime.analysis_history.status IS '状态：SUCCESS/PARTIAL/LIMITED/FAILED/RUNNING';
COMMENT ON COLUMN runtime.analysis_history.payload IS '历史结果 JSON 载荷';
COMMENT ON COLUMN runtime.analysis_history.created_at IS '创建时间';
