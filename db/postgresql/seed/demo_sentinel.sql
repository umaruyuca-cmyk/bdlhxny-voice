-- =============================================================================
-- seed/demo_sentinel.sql
-- 【演示数据，非生产事实】Sentinel 看护 Agent 演示种子。
--
-- 用途：空库按 db/execution/ 最新基线执行全部 schema + registry seed 后，
--       再执行本文件，即可获得可演示的持仓与稳健型风险画像。
-- 对齐：演示用户 ID = 1（与 deploy/.env.example 中 BDLH_RUNTIME_SINGLE_USER_ID=1 对齐）。
--
-- 纪律：
--   - 仅写 public.user_configs / public.portfolio_positions /
--     public.financial_profile_confirmations 三张既有表，不新增表。
--   - 目标记忆（如「两年内换房」）不落库——该事实经运行时确认卡写入 L3
--     （设计文档 §4.6）；演示时现场产生或经记忆候选接口注入。
--   - 本文件为演示数据，C-4 要求演示注入事件在事件层另行标记；
--     持仓与画像本身是「演示账户事实」，不在此处打 demo 水印。
--   - 头部 DELETE 守卫使本 seed 可在不清库的情况下重跑（仅清理 user_id=1）。
-- =============================================================================

BEGIN;

-- ── 清理守卫：仅清演示用户，保证可重跑 ──
DELETE FROM public.financial_profile_confirmations WHERE user_id = 1;
DELETE FROM public.portfolio_positions WHERE user_id = 1;
DELETE FROM public.user_configs WHERE user_id = 1;

-- =============================================================================
-- 1. 用户金融画像（稳健型 / moderate）
-- =============================================================================
INSERT INTO public.user_configs (
    user_id, monthly_budget, cash, currency, cash_reserve_ratio,
    risk_tolerance, max_loss_tolerance_pct, liquid_assets,
    near_term_cash_needs, near_term_cash_needs_horizon_days,
    financial_data_source, profile_version, confirmed_at, confirmation_ref,
    preferred_sectors, forbidden_symbols,
    notification_enabled, morning_brief_enabled, closing_summary_enabled,
    updated_at
) VALUES (
    1,
    8000,                       -- 月度可投资预算（CNY）
    200000,                     -- 现金余额
    'CNY',
    0.30,                       -- 现金储备比例 30%
    'moderate',                 -- 风险承受等级：稳健型（与 Java RISK_LEVELS 对齐）
    15.0000,                    -- 最大可承受亏损 15%
    1000000,                    -- 流动资产总额
    200000,                     -- 近期现金需求金额（数值事实；用途「换房」属 L3 目标记忆，不落库）
    730,                        -- 近期现金需求展望 730 天（约两年）
    'USER_INPUT',
    1,                          -- 画像版本号
    NOW(),
    'demo-confirm-001',         -- 确认单号
    '电力设备,食品饮料,银行',     -- 偏好行业
    NULL,                       -- 无禁投标的
    TRUE,                       -- 开启通知
    TRUE,                       -- 开启早报
    TRUE,                       -- 开启收盘摘要
    NOW()
);

-- =============================================================================
-- 2. 持仓 4 只（须含宁德时代 300750，对应演示剧本 §8 场景 #2 注入 -5.2%）
--    target_weight 为目标权重；当前权重由运行时按行情重算（portfolio.build_current_valuation）
-- =============================================================================
INSERT INTO public.portfolio_positions (
    user_id, code, name, asset_type, avg_cost, shares, buy_date,
    target_weight, sector, risk_role, exchange, currency,
    data_source, confirmed_at, source_ref, active
) VALUES
    (
        1, '300750', '宁德时代', 'EQUITY', 185.500000, 1000, DATE '2025-03-12',
        0.20, '电力设备', '核心', 'SZSE', 'CNY',
        'USER_INPUT', NOW(), 'demo-confirm-001', TRUE
    ),
    (
        1, '600519', '贵州茅台', 'EQUITY', 1680.000000, 100, DATE '2024-09-03',
        0.30, '食品饮料', '核心', 'SSE', 'CNY',
        'USER_INPUT', NOW(), 'demo-confirm-001', TRUE
    ),
    (
        1, '600036', '招商银行', 'EQUITY', 35.200000, 3000, DATE '2025-01-08',
        0.25, '银行', '卫星', 'SSE', 'CNY',
        'USER_INPUT', NOW(), 'demo-confirm-001', TRUE
    ),
    (
        1, '000333', '美的集团', 'EQUITY', 62.800000, 1500, DATE '2025-05-20',
        0.25, '家电', '卫星', 'SZSE', 'CNY',
        'USER_INPUT', NOW(), 'demo-confirm-001', TRUE
    );

-- =============================================================================
-- 3. 金融资料确认审计（与 user_configs.profile_version / confirmation_ref 对齐）
--    使画像处于「已确认」状态，数据面画像接口返回完整可演示快照。
-- =============================================================================
INSERT INTO public.financial_profile_confirmations (
    confirmation_ref, user_id, profile_version, action_type,
    idempotency_key, request_fingerprint, changed_fields, confirmed_at
) VALUES (
    'demo-confirm-001',
    1,
    1,
    'CONFIRM_PROFILE',
    'demo-idem-001',
    'demo-fingerprint-001',
    'risk_tolerance,cash,liquid_assets,positions',
    NOW()
);

COMMIT;
