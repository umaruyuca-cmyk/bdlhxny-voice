-- =============================================================================
-- financial_user_data.sql
-- L4 用户金融事实：画像配置、持仓、确认审计。
-- 表在 public schema，与 Java @TableName 一致。
-- =============================================================================

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

COMMENT ON TABLE public.user_configs IS '用户金融画像与账户偏好（USER_CONFIRMED 事实）';
COMMENT ON COLUMN public.user_configs.user_id IS '用户 ID';
COMMENT ON COLUMN public.user_configs.monthly_budget IS '月度可投资预算';
COMMENT ON COLUMN public.user_configs.cash IS '现金余额';
COMMENT ON COLUMN public.user_configs.currency IS '现金币种，如 CNY';
COMMENT ON COLUMN public.user_configs.cash_reserve_ratio IS '现金储备比例（0~1）';
COMMENT ON COLUMN public.user_configs.risk_tolerance IS '风险承受等级字面量';
COMMENT ON COLUMN public.user_configs.max_loss_tolerance_pct IS '最大可承受亏损百分比';
COMMENT ON COLUMN public.user_configs.liquid_assets IS '流动资产总额';
COMMENT ON COLUMN public.user_configs.near_term_cash_needs IS '近期现金需求金额';
COMMENT ON COLUMN public.user_configs.near_term_cash_needs_horizon_days IS '近期现金需求展望天数';
COMMENT ON COLUMN public.user_configs.financial_data_source IS '数据来源标记，如 USER_INPUT';
COMMENT ON COLUMN public.user_configs.profile_version IS '画像版本号（确认时递增）';
COMMENT ON COLUMN public.user_configs.confirmed_at IS '最近确认时间';
COMMENT ON COLUMN public.user_configs.confirmation_ref IS '最近确认单号';
COMMENT ON COLUMN public.user_configs.preferred_sectors IS '偏好行业（序列化文本）';
COMMENT ON COLUMN public.user_configs.forbidden_symbols IS '禁投标的（序列化文本）';
COMMENT ON COLUMN public.user_configs.notification_enabled IS '是否开启通知';
COMMENT ON COLUMN public.user_configs.morning_brief_enabled IS '是否开启早报';
COMMENT ON COLUMN public.user_configs.closing_summary_enabled IS '是否开启收盘摘要';
COMMENT ON COLUMN public.user_configs.updated_at IS '最近更新时间';

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

COMMENT ON TABLE public.portfolio_positions IS '用户持仓行（软删除用 active=false）';
COMMENT ON COLUMN public.portfolio_positions.id IS '持仓行主键';
COMMENT ON COLUMN public.portfolio_positions.user_id IS '用户 ID';
COMMENT ON COLUMN public.portfolio_positions.code IS '证券代码';
COMMENT ON COLUMN public.portfolio_positions.name IS '证券名称';
COMMENT ON COLUMN public.portfolio_positions.asset_type IS '资产类型，如 EQUITY';
COMMENT ON COLUMN public.portfolio_positions.avg_cost IS '平均成本价';
COMMENT ON COLUMN public.portfolio_positions.shares IS '持仓数量';
COMMENT ON COLUMN public.portfolio_positions.buy_date IS '建仓/买入日期';
COMMENT ON COLUMN public.portfolio_positions.target_weight IS '目标权重（0~1）';
COMMENT ON COLUMN public.portfolio_positions.sector IS '行业';
COMMENT ON COLUMN public.portfolio_positions.risk_role IS '组合中的风险角色标签';
COMMENT ON COLUMN public.portfolio_positions.exchange IS '交易所，如 SSE/SZSE';
COMMENT ON COLUMN public.portfolio_positions.currency IS '计价币种';
COMMENT ON COLUMN public.portfolio_positions.data_source IS '数据来源，如 USER_INPUT';
COMMENT ON COLUMN public.portfolio_positions.confirmed_at IS '用户确认时间';
COMMENT ON COLUMN public.portfolio_positions.source_ref IS '来源确认/凭证引用';
COMMENT ON COLUMN public.portfolio_positions.active IS '是否有效持仓；FALSE 表示软删除';
COMMENT ON COLUMN public.portfolio_positions.created_at IS '创建时间';
COMMENT ON COLUMN public.portfolio_positions.updated_at IS '最近更新时间';

CREATE TABLE IF NOT EXISTS public.portfolio_transactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    name VARCHAR(128),
    transaction_type VARCHAR(32) NOT NULL,
    quantity NUMERIC(20, 6),
    price NUMERIC(20, 6),
    amount NUMERIC(20, 4),
    currency VARCHAR(8),
    trade_date DATE NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_portfolio_transactions_user_trade_date
    ON public.portfolio_transactions(user_id, trade_date DESC, id DESC);

COMMENT ON TABLE public.portfolio_transactions IS '已发生交易的历史记录（只读查询，不承载交易执行）';
COMMENT ON COLUMN public.portfolio_transactions.id IS '交易记录主键';
COMMENT ON COLUMN public.portfolio_transactions.user_id IS '用户 ID';
COMMENT ON COLUMN public.portfolio_transactions.symbol IS '证券代码';
COMMENT ON COLUMN public.portfolio_transactions.name IS '证券名称';
COMMENT ON COLUMN public.portfolio_transactions.transaction_type IS '交易类型，如 BUY/SELL/DIVIDEND';
COMMENT ON COLUMN public.portfolio_transactions.quantity IS '成交数量';
COMMENT ON COLUMN public.portfolio_transactions.price IS '成交单价';
COMMENT ON COLUMN public.portfolio_transactions.amount IS '成交金额';
COMMENT ON COLUMN public.portfolio_transactions.currency IS '计价币种，如 CNY';
COMMENT ON COLUMN public.portfolio_transactions.trade_date IS '交易日期';
COMMENT ON COLUMN public.portfolio_transactions.note IS '备注';
COMMENT ON COLUMN public.portfolio_transactions.created_at IS '记录写入时间';

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

COMMENT ON TABLE public.financial_profile_confirmations IS '金融资料确认审计：幂等与版本轨迹';
COMMENT ON COLUMN public.financial_profile_confirmations.confirmation_ref IS '确认单号（主键）';
COMMENT ON COLUMN public.financial_profile_confirmations.user_id IS '用户 ID';
COMMENT ON COLUMN public.financial_profile_confirmations.profile_version IS '确认后的画像版本';
COMMENT ON COLUMN public.financial_profile_confirmations.action_type IS '动作类型，如 CONFIRM_PROFILE / UPSERT_POSITIONS';
COMMENT ON COLUMN public.financial_profile_confirmations.idempotency_key IS '客户端幂等键';
COMMENT ON COLUMN public.financial_profile_confirmations.request_fingerprint IS '请求指纹（防重复变体）';
COMMENT ON COLUMN public.financial_profile_confirmations.changed_fields IS '变更字段列表（序列化文本）';
COMMENT ON COLUMN public.financial_profile_confirmations.confirmed_at IS '确认时间';
