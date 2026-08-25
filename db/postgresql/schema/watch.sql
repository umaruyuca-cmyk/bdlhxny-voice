-- =============================================================================
-- watch.sql
-- 看护环数据表：监视规则（watch_rule）与事件流水（watch_event）。
-- 设计文档 §5、§4.8。两表落 runtime schema。
--
-- 关键语义：
--   - watch_event.dedupe_key 上唯一约束 = 幂等投递的物理承载（§4.8、D-5）；
--   - watch_event.source 取值含 demo_inject（C-4：演示注入全程可辨识）；
--   - watch_event.rule_id 不加外键约束——规则可删除而事件留作审计。
-- =============================================================================

-- ---------------------------------------------------------------------------
-- watch_rule：监视规则（持久化，跨进程存活）
--   type=price_threshold:     config={symbol, direction, pct|abs_price}
--   type=daily_briefing:       config={time, only_trading_day}
--   type=post_market_review:   config={time, only_trading_day}
-- ---------------------------------------------------------------------------
CREATE TABLE runtime.watch_rule (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    type VARCHAR(32) NOT NULL CHECK (
        type IN ('price_threshold', 'daily_briefing', 'post_market_review')
    ),
    config JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    last_fired_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runtime_watch_rule_user_status
    ON runtime.watch_rule(user_id, status);

CREATE INDEX idx_runtime_watch_rule_type_status
    ON runtime.watch_rule(type, status)
    WHERE status = 'active';

COMMENT ON TABLE runtime.watch_rule IS '监视规则：价格阈值 / 晨报 / 盘后复盘，跨进程存活';
COMMENT ON COLUMN runtime.watch_rule.id IS '规则 ID';
COMMENT ON COLUMN runtime.watch_rule.user_id IS '用户 ID（字符串形态，与 runtime schema 其它表一致）';
COMMENT ON COLUMN runtime.watch_rule.type IS '规则类型：price_threshold / daily_briefing / post_market_review';
COMMENT ON COLUMN runtime.watch_rule.config IS '规则配置 JSON：price_threshold={symbol,direction,pct|abs_price}；cron 类={time,only_trading_day}';
COMMENT ON COLUMN runtime.watch_rule.status IS '规则状态：active / paused';
COMMENT ON COLUMN runtime.watch_rule.last_fired_at IS '最近一次触发时间（边沿触发去重的联合判定输入）';
COMMENT ON COLUMN runtime.watch_rule.created_at IS '创建时间';
COMMENT ON COLUMN runtime.watch_rule.updated_at IS '最近更新时间';

-- ---------------------------------------------------------------------------
-- watch_event：事件流水（边沿触发 + 幂等投递）
--   dedupe_key = 规则 × 触发窗口 × 方向（§4.8），唯一约束强制幂等
--   source 取值：market_poll（价格轮询）/ cron（定时）/ demo_inject（演示注入，C-4）
-- ---------------------------------------------------------------------------
CREATE TABLE runtime.watch_event (
    id BIGSERIAL PRIMARY KEY,
    rule_id BIGINT NOT NULL,
    type VARCHAR(32) NOT NULL CHECK (
        type IN ('price_threshold', 'daily_briefing', 'post_market_review')
    ),
    source VARCHAR(32) NOT NULL CHECK (source IN ('market_poll', 'cron', 'demo_inject')),
    payload JSONB NOT NULL,
    dedupe_key VARCHAR(255) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX uq_runtime_watch_event_dedupe_key
    ON runtime.watch_event(dedupe_key);

CREATE INDEX idx_runtime_watch_event_rule_occurred
    ON runtime.watch_event(rule_id, occurred_at DESC);

CREATE INDEX idx_runtime_watch_event_type_occurred
    ON runtime.watch_event(type, occurred_at DESC);

COMMENT ON TABLE runtime.watch_event IS '看护事件流水：边沿触发产出，dedupe_key 唯一约束承载幂等';
COMMENT ON COLUMN runtime.watch_event.id IS '事件 ID';
COMMENT ON COLUMN runtime.watch_event.rule_id IS '来源规则 ID（无外键约束：规则可删而事件留作审计）';
COMMENT ON COLUMN runtime.watch_event.type IS '事件类型：price_threshold / daily_briefing / post_market_review';
COMMENT ON COLUMN runtime.watch_event.source IS '事件来源：market_poll / cron / demo_inject（C-4 演示注入标记）';
COMMENT ON COLUMN runtime.watch_event.payload IS '事件负载 JSON（仅触发事实，资讯内容由唤醒后 Agent 现取）';
COMMENT ON COLUMN runtime.watch_event.dedupe_key IS '去重键（规则 × 触发窗口 × 方向），唯一约束强制幂等（§4.8、D-5）';
COMMENT ON COLUMN runtime.watch_event.occurred_at IS '事件发生时间';
COMMENT ON COLUMN runtime.watch_event.created_at IS '记录写入时间';
