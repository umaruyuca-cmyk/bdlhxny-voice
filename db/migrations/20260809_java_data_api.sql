-- Java Data API 增量迁移：风险偏好 + 已发生交易历史。
-- 可重复执行；仅增加只读分析所需的数据结构，不创建订单或交易执行表。

ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS risk_tolerance VARCHAR(20);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS preferred_sectors VARCHAR(500);
ALTER TABLE public.user_configs
    ADD COLUMN IF NOT EXISTS forbidden_symbols VARCHAR(500);

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
