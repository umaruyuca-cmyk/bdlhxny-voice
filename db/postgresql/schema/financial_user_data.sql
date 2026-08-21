-- 用户金融资料与持仓（L4 事实表；供 Suitability USER_CONFIRMED 路径使用）
-- 表落在 public schema，与当前 Java @TableName 一致。

CREATE TABLE IF NOT EXISTS public.user_configs (
    user_id BIGINT PRIMARY KEY,
    monthly_budget INTEGER,
    cash NUMERIC(20, 4),
    currency VARCHAR(8),
    cash_reserve_ratio NUMERIC(10, 6),
    risk_tolerance VARCHAR(32),
    max_loss_tolerance_pct NUMERIC(10, 4),
    liquid_assets NUMERIC(20, 4),
    near_term_cash_needs NUMERIC(20, 4),
    near_term_cash_needs_horizon_days INTEGER,
    financial_data_source VARCHAR(32),
    profile_version BIGINT NOT NULL DEFAULT 0,
    confirmed_at TIMESTAMPTZ,
    confirmation_ref VARCHAR(64),
    preferred_sectors TEXT,
    forbidden_symbols TEXT,
    notification_enabled BOOLEAN,
    morning_brief_enabled BOOLEAN,
    closing_summary_enabled BOOLEAN,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.portfolio_positions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    code VARCHAR(32) NOT NULL,
    name VARCHAR(128),
    asset_type VARCHAR(32) NOT NULL,
    avg_cost NUMERIC(20, 6),
    shares NUMERIC(20, 6),
    buy_date DATE,
    target_weight NUMERIC(10, 6),
    sector VARCHAR(64),
    risk_role VARCHAR(64),
    exchange VARCHAR(16),
    currency VARCHAR(8),
    data_source VARCHAR(32),
    confirmed_at TIMESTAMPTZ,
    source_ref VARCHAR(64),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_portfolio_positions_user_active
    ON public.portfolio_positions(user_id, active);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_positions_user_code_active
    ON public.portfolio_positions(user_id, code)
    WHERE active IS TRUE;

CREATE TABLE IF NOT EXISTS public.financial_profile_confirmations (
    confirmation_ref VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    profile_version BIGINT NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(100) NOT NULL,
    request_fingerprint VARCHAR(128) NOT NULL,
    changed_fields TEXT,
    confirmed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_profile_confirmations_user_idempotency
    ON public.financial_profile_confirmations(user_id, idempotency_key);

CREATE INDEX IF NOT EXISTS idx_financial_profile_confirmations_user_confirmed
    ON public.financial_profile_confirmations(user_id, confirmed_at DESC);
