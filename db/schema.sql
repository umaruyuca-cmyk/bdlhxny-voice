-- ============================================================
-- StockWise 数据库初始化脚本
-- PostgreSQL 16 + PgVector
-- 本脚本采用 IF NOT EXISTS，可安全重复执行；已有对象不会被覆盖或自动迁移。
-- ============================================================

-- 所有业务对象固定创建在 public Schema，避免依赖客户端 search_path。
CREATE SCHEMA IF NOT EXISTS public;
SET search_path TO public, pg_catalog;

-- 启用扩展
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;

-- ============================================================
-- 1. 用户表（已迁移到 MySQL，见 mysql-schema.sql）
-- ============================================================

-- ============================================================
-- 2. 持仓配置
-- ============================================================
CREATE TABLE IF NOT EXISTS public.portfolio_positions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    code            VARCHAR(32) NOT NULL,
    name            VARCHAR(100) NOT NULL,
    asset_type      VARCHAR(20) NOT NULL CHECK (asset_type IN ('stock','etf','open_fund','qdii')),
    avg_cost        DECIMAL(12,4) NOT NULL,
    shares          DECIMAL(16,4) NOT NULL,
    buy_date        DATE NOT NULL,
    target_weight   DECIMAL(5,4) NOT NULL DEFAULT 0,
    sector          VARCHAR(50),
    risk_role       VARCHAR(30),
    exchange        VARCHAR(16),
    currency        VARCHAR(8),
    data_source     VARCHAR(24)
                    CHECK (data_source IS NULL OR data_source IN ('USER_INPUT','BROKER_SYNC','ACCOUNT_PROVIDER','TEST_FIXTURE')),
    confirmed_at    TIMESTAMPTZ,
    source_ref      VARCHAR(100),
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, code)
);

COMMENT ON TABLE public.portfolio_positions IS '用户持仓配置表';
COMMENT ON COLUMN public.portfolio_positions.shares IS '持仓份额（股票:股，基金:份数）';

-- ============================================================
-- 3. 用户配置
-- ============================================================
CREATE TABLE IF NOT EXISTS public.user_configs (
    user_id               BIGINT PRIMARY KEY,
    monthly_budget        INT DEFAULT 5000,
    cash                  DECIMAL(14,2) DEFAULT 0,
    currency              VARCHAR(8),
    cash_reserve_ratio    DECIMAL(4,3) DEFAULT 0.20,
    risk_tolerance        VARCHAR(20),
    max_loss_tolerance_pct DECIMAL(5,2)
                    CHECK (max_loss_tolerance_pct IS NULL OR (max_loss_tolerance_pct >= 0 AND max_loss_tolerance_pct <= 100)),
    liquid_assets         DECIMAL(16,2) CHECK (liquid_assets IS NULL OR liquid_assets >= 0),
    near_term_cash_needs  DECIMAL(16,2) CHECK (near_term_cash_needs IS NULL OR near_term_cash_needs >= 0),
    near_term_cash_needs_horizon_days INT
                    CHECK (near_term_cash_needs_horizon_days IS NULL OR near_term_cash_needs_horizon_days > 0),
    financial_data_source VARCHAR(24)
                    CHECK (financial_data_source IS NULL OR financial_data_source IN ('USER_INPUT','BROKER_SYNC','ACCOUNT_PROVIDER','TEST_FIXTURE')),
    profile_version       BIGINT NOT NULL DEFAULT 0,
    confirmed_at          TIMESTAMPTZ,
    confirmation_ref      VARCHAR(100),
    preferred_sectors     VARCHAR(500),
    forbidden_symbols     VARCHAR(500),
    notification_enabled  BOOLEAN DEFAULT TRUE,
    morning_brief_enabled BOOLEAN DEFAULT TRUE,
    closing_summary_enabled BOOLEAN DEFAULT TRUE,
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

-- 旧库不会因 CREATE TABLE IF NOT EXISTS 自动补齐新增资金字段，显式增量升级。
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS cash DECIMAL(14,2) DEFAULT 0;
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS cash_reserve_ratio DECIMAL(4,3) DEFAULT 0.20;
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS risk_tolerance VARCHAR(20);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS preferred_sectors VARCHAR(500);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS forbidden_symbols VARCHAR(500);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS currency VARCHAR(8);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS max_loss_tolerance_pct DECIMAL(5,2);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS liquid_assets DECIMAL(16,2);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS near_term_cash_needs DECIMAL(16,2);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS near_term_cash_needs_horizon_days INT;
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS financial_data_source VARCHAR(24);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS profile_version BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS confirmation_ref VARCHAR(100);

ALTER TABLE public.portfolio_positions
    ADD COLUMN IF NOT EXISTS exchange VARCHAR(16);
ALTER TABLE public.portfolio_positions
    ADD COLUMN IF NOT EXISTS currency VARCHAR(8);
ALTER TABLE public.portfolio_positions
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(24);
ALTER TABLE public.portfolio_positions
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;
ALTER TABLE public.portfolio_positions
    ADD COLUMN IF NOT EXISTS source_ref VARCHAR(100);

COMMENT ON TABLE public.user_configs IS '用户偏好配置表';
COMMENT ON COLUMN public.user_configs.cash_reserve_ratio IS '现金保留比例，最低0.15';
COMMENT ON COLUMN public.user_configs.max_loss_tolerance_pct IS '用户明确确认的最大亏损容忍百分数点，0到100；不是现金保留比例';
COMMENT ON COLUMN public.user_configs.near_term_cash_needs IS '用户明确确认的近期现金需求金额；不是月度投资预算';
COMMENT ON COLUMN public.portfolio_positions.target_weight IS '目标权重，不是当前实际权重';
COMMENT ON COLUMN public.portfolio_positions.avg_cost IS '持仓成本价，不是当前市场价格';

CREATE TABLE IF NOT EXISTS public.financial_profile_confirmations (
    confirmation_ref   VARCHAR(100) PRIMARY KEY,
    user_id            BIGINT NOT NULL,
    profile_version    BIGINT NOT NULL CHECK (profile_version > 0),
    action_type        VARCHAR(40) NOT NULL
                       CHECK (action_type IN ('FINANCIAL_PROFILE_REPLACE','PORTFOLIO_POSITIONS_REPLACE')),
    idempotency_key    VARCHAR(100) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    changed_fields     VARCHAR(1000) NOT NULL,
    confirmed_at       TIMESTAMPTZ NOT NULL,
    UNIQUE(user_id, profile_version),
    UNIQUE(user_id, idempotency_key)
);

COMMENT ON TABLE public.financial_profile_confirmations IS
    '用户金融资料确认审计；只保存版本、字段路径与请求指纹，不复制完整敏感金融载荷';

-- ============================================================
-- 3.1 已发生交易历史（只读分析输入，不是订单表）
-- ============================================================
CREATE TABLE IF NOT EXISTS public.portfolio_transactions (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT NOT NULL,
    symbol           VARCHAR(12) NOT NULL,
    name             VARCHAR(100),
    transaction_type VARCHAR(20) NOT NULL
        CHECK (transaction_type IN ('BUY','SELL','DIVIDEND','FEE','TRANSFER')),
    quantity         DECIMAL(16,4),
    price            DECIMAL(14,4),
    amount           DECIMAL(16,2),
    currency         VARCHAR(8) NOT NULL DEFAULT 'CNY',
    trade_date       DATE NOT NULL,
    note             VARCHAR(500),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pt_user_trade_date
    ON public.portfolio_transactions(user_id, trade_date DESC, id DESC);

COMMENT ON TABLE public.portfolio_transactions IS
    '已发生交易的只读历史，仅供分析，不代表订单或交易执行';

-- ============================================================
-- 4. 分析历史
-- ============================================================
CREATE TABLE IF NOT EXISTS public.analysis_history (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    type          VARCHAR(20) NOT NULL CHECK (type IN ('portfolio','stock','sector','briefing','closing_summary')),
    code          VARCHAR(6),
    result_json   JSONB NOT NULL,
    token_used    INT DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ah_user_time ON public.analysis_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ah_user_type ON public.analysis_history(user_id, type);
CREATE INDEX IF NOT EXISTS idx_ah_created ON public.analysis_history(created_at DESC);

COMMENT ON TABLE public.analysis_history IS '分析历史记录表';

-- ============================================================
-- 5. 对话历史（中期记忆持久化）
-- ============================================================
CREATE TABLE IF NOT EXISTS public.conversation_history (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    session_id    VARCHAR(64) NOT NULL,
    messages      JSONB NOT NULL,
    summary       TEXT,
    token_count   INT DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ch_session ON public.conversation_history(session_id);
CREATE INDEX IF NOT EXISTS idx_ch_user_session ON public.conversation_history(user_id, session_id);

COMMENT ON TABLE public.conversation_history IS '对话历史记录表（中期记忆）';
COMMENT ON COLUMN public.conversation_history.messages IS '完整对话消息JSON数组';
COMMENT ON COLUMN public.conversation_history.summary IS 'LLM压缩后的对话摘要（超5轮时生成）';

-- ============================================================
-- 5.1 会话目录（前端左侧会话列表的持久化真相源）
-- ============================================================
CREATE TABLE IF NOT EXISTS public.conversation_sessions (
    session_id    VARCHAR(100) PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    mode          VARCHAR(32) NOT NULL,
    title         VARCHAR(200) NOT NULL,
    message_count INT NOT NULL DEFAULT 0,
    status        VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_user_updated
    ON public.conversation_sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_cs_user_mode_updated
    ON public.conversation_sessions(user_id, mode, updated_at DESC);

COMMENT ON TABLE public.conversation_sessions IS 'Agent 会话目录，保存标题、模式和最近更新时间，不替代完整消息历史';
COMMENT ON COLUMN public.conversation_sessions.session_id IS '与 Redis 工作记忆和 conversation_history 一致的后端会话 ID';

CREATE TABLE IF NOT EXISTS public.conversation_session_snapshots (
    session_id    VARCHAR(100) PRIMARY KEY
                  REFERENCES public.conversation_sessions(session_id) ON DELETE CASCADE,
    user_id       BIGINT NOT NULL,
    messages      JSONB NOT NULL,
    token_count   INT NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.conversation_session_snapshots IS '每个活动会话的最新完整消息快照，不参与长期情景向量归档';

-- ============================================================
-- 5.0 会话情景向量（LangChain4j 长期记忆检索层）
-- ============================================================
-- conversation_history 继续保存完整会话并作为真相源；本表只保存可重建的摘要向量索引。
-- 向量生成或索引写入失败不得影响完整会话归档。
CREATE TABLE IF NOT EXISTS public.conversation_episode_embeddings (
    id                       BIGSERIAL PRIMARY KEY,
    embedding_id             VARCHAR(64) NOT NULL UNIQUE,
    conversation_history_id  BIGINT NOT NULL UNIQUE
                             REFERENCES public.conversation_history(id) ON DELETE CASCADE,
    user_id                  BIGINT NOT NULL,
    session_id               VARCHAR(64) NOT NULL,
    symbol                   VARCHAR(12),
    content                  TEXT NOT NULL,
    embedding                VECTOR(1024) NOT NULL,
    metadata                 JSONB NOT NULL DEFAULT '{}',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cee_user_time
    ON public.conversation_episode_embeddings(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cee_user_symbol_time
    ON public.conversation_episode_embeddings(user_id, symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cee_metadata
    ON public.conversation_episode_embeddings USING GIN (metadata);
CREATE INDEX IF NOT EXISTS idx_cee_embedding
    ON public.conversation_episode_embeddings
    USING hnsw (embedding vector_cosine_ops);

COMMENT ON TABLE public.conversation_episode_embeddings IS 'LangChain4j情景记忆向量索引，可从conversation_history重建';
COMMENT ON COLUMN public.conversation_episode_embeddings.content IS '会话的可检索摘要，不替代完整消息';
COMMENT ON COLUMN public.conversation_episode_embeddings.embedding IS 'text-embedding-v4生成的1024维摘要向量';

-- ============================================================
-- 5.0.1 用户结构化反馈（情景记忆）
-- ============================================================
CREATE TABLE IF NOT EXISTS public.user_feedback (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL,
    session_id     VARCHAR(64) NOT NULL,
    run_id         UUID,
    feedback_type  VARCHAR(30) NOT NULL
                   CHECK (feedback_type IN (
                       'RESOLVED','UNRESOLVED','CORRECTION',
                       'KNOWLEDGE_CONFIRMED','KNOWLEDGE_REJECTED'
                   )),
    message         TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_user_time
    ON public.user_feedback(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_feedback_session
    ON public.user_feedback(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_feedback_run
    ON public.user_feedback(run_id) WHERE run_id IS NOT NULL;

COMMENT ON TABLE public.user_feedback IS '用户对回答与知识沉淀的结构化反馈情景记忆';

-- ============================================================
-- 5.1 Agent 运行审计与 ReAct 回放
-- ============================================================
CREATE TABLE IF NOT EXISTS public.agent_runs (
    run_id           UUID PRIMARY KEY,
    user_id          BIGINT NOT NULL,
    session_id       VARCHAR(64) NOT NULL,
    intent           VARCHAR(40),
    skill_name       VARCHAR(80) NOT NULL,
    skill_version    VARCHAR(20) NOT NULL DEFAULT '1.0',
    status           VARCHAR(20) NOT NULL
                     CHECK (status IN ('running','completed','failed','cancelled')),
    request_text     TEXT NOT NULL,
    final_answer     TEXT,
    max_tool_calls   INT NOT NULL DEFAULT 0 CHECK (max_tool_calls >= 0),
    tool_call_count  INT NOT NULL DEFAULT 0 CHECK (tool_call_count >= 0),
    error_message    TEXT,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_time ON public.agent_runs(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON public.agent_runs(session_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON public.agent_runs(status, started_at DESC);

COMMENT ON TABLE public.agent_runs IS '一次 Skill 推理对应的 Agent Run，用于审计、指标和回放';
COMMENT ON COLUMN public.agent_runs.final_answer IS '最终展示给用户的回答，不保存模型隐藏思维链';

CREATE TABLE IF NOT EXISTS public.agent_steps (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID NOT NULL REFERENCES public.agent_runs(run_id) ON DELETE CASCADE,
    step_no     INT NOT NULL CHECK (step_no > 0),
    step_type   VARCHAR(30) NOT NULL
                CHECK (step_type IN (
                    'TOOL_CALL','TOOL_OBSERVATION','POLICY_REJECTION',
                    'ROUTE_DECISION','REACT_DECISION','REACT_TERMINATION',
                    'MODEL_GATE','MODEL_CALL','FINAL_ANSWER','ERROR'
                )),
    name        VARCHAR(100),
    summary     TEXT,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, step_no)
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run ON public.agent_steps(run_id, step_no);

COMMENT ON TABLE public.agent_steps IS 'Agent Run 的有序可回放步骤，只保存动作、Observation 和简短摘要';

-- 旧库中的 CHECK 不会被 CREATE TABLE IF NOT EXISTS 自动升级，显式重建且可重复执行。
ALTER TABLE public.agent_steps DROP CONSTRAINT IF EXISTS agent_steps_step_type_check;
ALTER TABLE public.agent_steps ADD CONSTRAINT agent_steps_step_type_check
    CHECK (step_type IN (
        'TOOL_CALL','TOOL_OBSERVATION','POLICY_REJECTION',
        'ROUTE_DECISION','REACT_DECISION','REACT_TERMINATION',
        'MODEL_GATE','MODEL_CALL','FINAL_ANSWER','ERROR'
    ));

CREATE TABLE IF NOT EXISTS public.tool_executions (
    id                BIGSERIAL PRIMARY KEY,
    run_id            UUID NOT NULL REFERENCES public.agent_runs(run_id) ON DELETE CASCADE,
    call_step_no      INT NOT NULL CHECK (call_step_no > 0),
    observation_step_no INT CHECK (observation_step_no > 0),
    tool_name         VARCHAR(100) NOT NULL,
    argument_json     JSONB NOT NULL DEFAULT '{}',
    observation_json  JSONB,
    status            VARCHAR(20) NOT NULL
                      CHECK (status IN ('running','success','failed','rejected')),
    duration_ms       BIGINT CHECK (duration_ms >= 0),
    error_code        VARCHAR(80),
    error_message     TEXT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tool_executions_run ON public.tool_executions(run_id, call_step_no);
CREATE INDEX IF NOT EXISTS idx_tool_executions_tool ON public.tool_executions(tool_name, started_at DESC);

COMMENT ON TABLE public.tool_executions IS '工具 Action 与 Observation 的结构化执行记录';

-- ============================================================
-- 6. 知识库 Chunk（PgVector 向量存储，v3：解决驱动型知识沉淀）
-- ============================================================
-- v3 变更：取消 v2 的"文档(document)→分块(chunk)"两层结构，
-- 知识按"被解决的问题"直接沉淀为一条 chunk，生命周期信息记入 metadata + status。
CREATE TABLE IF NOT EXISTS public.knowledge_chunks (
    id            BIGSERIAL PRIMARY KEY,
    content       TEXT NOT NULL,
    embedding     VECTOR(1024),  -- qwen3-embedding:0.6b 原生1024维（MRL 可自定义 32-1024）
    metadata      JSONB DEFAULT '{}',
    status        VARCHAR(20) DEFAULT 'active'
                  CHECK (status IN ('active','expired','conflicted','deprecated')),
    version       INT DEFAULT 1,
    replaces_id   BIGINT REFERENCES public.knowledge_chunks(id),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- metadata JSON 结构（v3 解决驱动型沉淀）:
-- { "source": "resolved", "problem": "原始问题", "confidence": 85,
--   "expires_at": "2027-07-24T00:00:00Z", "tags": [...], "user_id": "u_001" }

-- PgVector IVFFlat 索引（余弦相似度）
CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx ON public.knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- 状态索引（Step 5 质量过滤：仅检索 active）
CREATE INDEX IF NOT EXISTS idx_kc_status ON public.knowledge_chunks(status);

-- PostgreSQL 全文检索索引（混合检索）
CREATE INDEX IF NOT EXISTS idx_kc_fts ON public.knowledge_chunks
    USING GIN (to_tsvector('simple', content));

-- 元数据过滤索引（按 tags/source/problem 过滤）
CREATE INDEX IF NOT EXISTS idx_kc_metadata ON public.knowledge_chunks USING GIN (metadata);

COMMENT ON TABLE public.knowledge_chunks IS '知识库向量存储表（v3 解决驱动型沉淀）';
COMMENT ON COLUMN public.knowledge_chunks.embedding IS 'text-embedding-v4: 1024维';
COMMENT ON COLUMN public.knowledge_chunks.status IS 'active/expired/conflicted/deprecated；检索时仅用 active';
COMMENT ON COLUMN public.knowledge_chunks.metadata IS 'JSON: source/problem/confidence/expires_at/tags/user_id';
COMMENT ON COLUMN public.knowledge_chunks.replaces_id IS '更新旧知识时，指向被替换的旧 chunk id';

-- ============================================================
-- 8. Token 消耗记录
-- ============================================================
CREATE TABLE IF NOT EXISTS public.token_usage_log (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    session_id    VARCHAR(64),
    model         VARCHAR(50),
    prompt_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens  INT DEFAULT 0,
    cost_estimate DECIMAL(10,6),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tul_user_date ON public.token_usage_log(user_id, created_at DESC);

COMMENT ON TABLE public.token_usage_log IS 'Token消耗审计日志';

-- ============================================================
-- 9. 定时任务执行记录
-- ============================================================
CREATE TABLE IF NOT EXISTS public.scheduled_task_log (
    id            BIGSERIAL PRIMARY KEY,
    task_type     VARCHAR(30) NOT NULL CHECK (task_type IN ('morning_brief','closing_summary','price_alert')),
    user_id       BIGINT,
    status        VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','success','failed')),
    result_json   JSONB,
    error_message TEXT,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stl_task_time ON public.scheduled_task_log(task_type, created_at DESC);

COMMENT ON TABLE public.scheduled_task_log IS '定时任务执行记录表';

-- ============================================================
-- 初始数据：示例用户在 MySQL（见 mysql-schema.sql），PG 不插入
-- ============================================================
