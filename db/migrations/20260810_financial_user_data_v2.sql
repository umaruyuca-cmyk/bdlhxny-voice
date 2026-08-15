-- M3 Java 用户金融事实 v2：只保存用户确认/受控同步事实，不保存派生市值或实际权重。
-- 可重复执行；旧记录不回填 data_source/currency/confirmed_at，避免伪造 USER_CONFIRMED/LIVE。

ALTER TABLE public.portfolio_positions
    ALTER COLUMN code TYPE VARCHAR(32);

ALTER TABLE public.portfolio_positions
    ADD COLUMN IF NOT EXISTS exchange VARCHAR(16),
    ADD COLUMN IF NOT EXISTS currency VARCHAR(8),
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(24),
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_ref VARCHAR(100);

ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS currency VARCHAR(8),
    ADD COLUMN IF NOT EXISTS max_loss_tolerance_pct DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS liquid_assets DECIMAL(16,2),
    ADD COLUMN IF NOT EXISTS near_term_cash_needs DECIMAL(16,2),
    ADD COLUMN IF NOT EXISTS near_term_cash_needs_horizon_days INT,
    ADD COLUMN IF NOT EXISTS financial_data_source VARCHAR(24),
    ADD COLUMN IF NOT EXISTS profile_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirmation_ref VARCHAR(100);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_pp_data_source_v2') THEN
        ALTER TABLE public.portfolio_positions
            ADD CONSTRAINT ck_pp_data_source_v2
            CHECK (data_source IS NULL OR data_source IN ('USER_INPUT','BROKER_SYNC','ACCOUNT_PROVIDER','TEST_FIXTURE'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_uc_max_loss_pct_v2') THEN
        ALTER TABLE public.user_configs
            ADD CONSTRAINT ck_uc_max_loss_pct_v2
            CHECK (max_loss_tolerance_pct IS NULL OR
                   (max_loss_tolerance_pct >= 0 AND max_loss_tolerance_pct <= 100));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_uc_liquid_assets_v2') THEN
        ALTER TABLE public.user_configs
            ADD CONSTRAINT ck_uc_liquid_assets_v2
            CHECK (liquid_assets IS NULL OR liquid_assets >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_uc_cash_needs_v2') THEN
        ALTER TABLE public.user_configs
            ADD CONSTRAINT ck_uc_cash_needs_v2
            CHECK (near_term_cash_needs IS NULL OR near_term_cash_needs >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_uc_cash_horizon_v2') THEN
        ALTER TABLE public.user_configs
            ADD CONSTRAINT ck_uc_cash_horizon_v2
            CHECK (near_term_cash_needs_horizon_days IS NULL OR near_term_cash_needs_horizon_days > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_uc_data_source_v2') THEN
        ALTER TABLE public.user_configs
            ADD CONSTRAINT ck_uc_data_source_v2
            CHECK (financial_data_source IS NULL OR financial_data_source IN
                   ('USER_INPUT','BROKER_SYNC','ACCOUNT_PROVIDER','TEST_FIXTURE'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.financial_profile_confirmations (
    confirmation_ref    VARCHAR(100) PRIMARY KEY,
    user_id             BIGINT NOT NULL,
    profile_version     BIGINT NOT NULL CHECK (profile_version > 0),
    action_type         VARCHAR(40) NOT NULL
                        CHECK (action_type IN ('FINANCIAL_PROFILE_REPLACE','PORTFOLIO_POSITIONS_REPLACE')),
    idempotency_key     VARCHAR(100) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    changed_fields      VARCHAR(1000) NOT NULL,
    confirmed_at        TIMESTAMPTZ NOT NULL,
    UNIQUE(user_id, profile_version),
    UNIQUE(user_id, idempotency_key)
);

COMMENT ON TABLE public.financial_profile_confirmations IS
    '用户金融资料确认审计；只保存版本、字段路径与请求指纹，不复制完整敏感金融载荷';
COMMENT ON COLUMN public.portfolio_positions.target_weight IS '目标权重，不是当前实际权重';
COMMENT ON COLUMN public.portfolio_positions.avg_cost IS '持仓成本价，不是当前市场价格';
COMMENT ON COLUMN public.user_configs.max_loss_tolerance_pct IS
    '用户明确确认的最大亏损容忍百分数点，0到100；不是现金保留比例';
COMMENT ON COLUMN public.user_configs.near_term_cash_needs IS
    '用户明确确认的近期现金需求金额；不是月度投资预算';
