-- =============================================================================
-- seed/registry.sql
-- Registry 全量目录种子（空库、schema 完成后执行一次）。
-- 不含 plugin-contract-probe；资格/预算/快路径不在 DB。
-- =============================================================================

-- Operation
INSERT INTO registry.bdlh_runtime_operation(code, description) VALUES
    ('READ_MARKET_DATA', '读取公开市场数据'),
    ('READ_PUBLIC_RESEARCH', '读取外部公开研究资料'),
    ('READ_PORTFOLIO', '读取用户持仓与账户'),
    ('READ_PROFILE', '读取用户风险画像'),
    ('READ_FINANCIAL_GOALS', '读取用户财务目标'),
    ('RUN_ANALYSIS', '执行确定性金融分析'),
    ('PROPOSE_TASK', '提议持续观察任务');

-- Toolset
INSERT INTO registry.bdlh_runtime_toolset(name, description) VALUES
    ('market_read', '读取标的、行情、历史价格和资金流数据'),
    ('fundamental_read', '读取财务报表、估值和行业背景数据'),
    ('news_read', '读取结构化新闻和外部公开资料'),
    ('portfolio_read', '只读访问当前用户持仓、账户和交易历史'),
    ('financial_profile_read', '只读访问当前用户风险画像和金融档案'),
    ('planning_compute', '对标准化数据执行确定性金融计算');

-- Capability
INSERT INTO registry.bdlh_runtime_capability
    (name, description, domain, adapter, read_only, requires_authenticated_user,
     required_arguments, depends_on, timeout_seconds, enabled)
VALUES
    ('market.resolve_instrument', '解析证券代码或名称并返回标准化标的信息', 'market', 'mcp', TRUE, FALSE, '{symbol}', '{}', 20, TRUE),
    ('market.get_realtime_quote', '获取指定标的的最新标准化行情', 'market', 'mcp', TRUE, FALSE, '{symbol}', '{market.resolve_instrument}', 20, TRUE),
    ('market.get_historical_prices', '获取指定标的的标准化历史 OHLCV 数据', 'market', 'mcp', TRUE, FALSE, '{symbol,lookback_days}', '{market.resolve_instrument}', 20, TRUE),
    ('market.get_financial_statements', '获取基本面分析所需的标准化财务报表数据', 'fundamental', 'mcp', TRUE, FALSE, '{symbol}', '{market.resolve_instrument}', 20, TRUE),
    ('market.get_valuation', '获取市盈率、市净率等标准化估值数据', 'fundamental', 'mcp', TRUE, FALSE, '{symbol}', '{market.resolve_instrument}', 20, TRUE),
    ('market.get_industry_context', '获取标的所属行业及行业背景', 'sector', 'mcp', TRUE, FALSE, '{symbol}', '{market.resolve_instrument}', 20, TRUE),
    ('market.get_money_flow', '获取标的资金流数据', 'market', 'mcp', TRUE, FALSE, '{symbol}', '{market.resolve_instrument}', 20, TRUE),
    ('market.get_news', '获取与标的相关的结构化新闻', 'research', 'mcp', TRUE, FALSE, '{symbol}', '{market.resolve_instrument}', 20, TRUE),
    ('research.web_search', '检索最新外部资料并返回带来源的标准化结果', 'research', 'web', TRUE, FALSE, '{query}', '{}', 20, TRUE),
    ('research.deep_search', '对研究任务做多轮拆题、检索、压缩并返回结构化 ResearchBundle', 'research', 'local', TRUE, FALSE, '{question,objective}', '{}', 90, TRUE),
    ('analysis.run_analysis', '对已标准化的数据执行确定性金融分析', 'analysis', 'local', TRUE, FALSE, '{}', '{}', 60, TRUE),
    ('portfolio.get_current_positions', '读取当前用户持仓', 'portfolio', 'java', TRUE, TRUE, '{}', '{}', 10, TRUE),
    ('portfolio.get_account_snapshot', '读取当前用户账户快照', 'portfolio', 'java', TRUE, TRUE, '{}', '{}', 10, TRUE),
    ('portfolio.get_transaction_history', '读取当前用户交易历史', 'portfolio', 'java', TRUE, TRUE, '{}', '{}', 10, TRUE),
    ('portfolio.build_current_valuation', '基于行情对当前持仓做确定性估值重算', 'portfolio', 'local', TRUE, TRUE, '{positions_observation,account_observation,quote_observations}', '{portfolio.get_current_positions,portfolio.get_account_snapshot}', 30, TRUE),
    ('user.get_risk_profile', '读取当前用户风险画像', 'user', 'java', TRUE, TRUE, '{}', '{}', 10, TRUE);

-- Capability → Operation
INSERT INTO registry.bdlh_runtime_capability_operation(capability_name, operation_code) VALUES
    ('market.resolve_instrument', 'READ_MARKET_DATA'),
    ('market.get_realtime_quote', 'READ_MARKET_DATA'),
    ('market.get_historical_prices', 'READ_MARKET_DATA'),
    ('market.get_financial_statements', 'READ_MARKET_DATA'),
    ('market.get_valuation', 'READ_MARKET_DATA'),
    ('market.get_industry_context', 'READ_MARKET_DATA'),
    ('market.get_money_flow', 'READ_MARKET_DATA'),
    ('market.get_news', 'READ_MARKET_DATA'),
    ('research.web_search', 'READ_PUBLIC_RESEARCH'),
    ('research.deep_search', 'READ_PUBLIC_RESEARCH'),
    ('analysis.run_analysis', 'RUN_ANALYSIS'),
    ('portfolio.get_current_positions', 'READ_PORTFOLIO'),
    ('portfolio.get_account_snapshot', 'READ_PORTFOLIO'),
    ('portfolio.get_transaction_history', 'READ_PORTFOLIO'),
    ('portfolio.build_current_valuation', 'READ_PORTFOLIO'),
    ('user.get_risk_profile', 'READ_PROFILE');

-- Capability → Toolset
INSERT INTO registry.bdlh_runtime_capability_toolset(capability_name, toolset_name) VALUES
    ('market.resolve_instrument', 'market_read'),
    ('market.get_realtime_quote', 'market_read'),
    ('market.get_historical_prices', 'market_read'),
    ('market.get_money_flow', 'market_read'),
    ('market.get_financial_statements', 'fundamental_read'),
    ('market.get_valuation', 'fundamental_read'),
    ('market.get_industry_context', 'fundamental_read'),
    ('market.get_news', 'news_read'),
    ('research.web_search', 'news_read'),
    ('research.deep_search', 'news_read'),
    ('analysis.run_analysis', 'planning_compute'),
    ('portfolio.get_current_positions', 'portfolio_read'),
    ('portfolio.get_account_snapshot', 'portfolio_read'),
    ('portfolio.get_transaction_history', 'portfolio_read'),
    ('portfolio.build_current_valuation', 'portfolio_read'),
    ('user.get_risk_profile', 'financial_profile_read');

-- Skill（stock-research + portfolio-health 默认启用；forecast 为第二 Domain 玩具 Skill；suitability 仍由请求快照路径驱动）
INSERT INTO registry.bdlh_runtime_skill(skill_id, skill_version, domain, status, enabled) VALUES
    ('stock-research', '1.0.0', 'finance', 'CURRENT', TRUE),
    ('portfolio-health', '1.0.0', 'finance', 'CURRENT', TRUE),
    ('suitability-evaluation', '1.0.0', 'finance', 'FOUNDATION', FALSE),
    ('forecast', '1.0.0', 'weather', 'EXPERIMENTAL', TRUE);

INSERT INTO registry.bdlh_runtime_skill_operation(skill_id, operation_code, required) VALUES
    ('stock-research', 'READ_MARKET_DATA', TRUE),
    ('stock-research', 'RUN_ANALYSIS', TRUE),
    ('stock-research', 'READ_PUBLIC_RESEARCH', FALSE),
    ('portfolio-health', 'READ_PORTFOLIO', TRUE),
    ('portfolio-health', 'READ_PROFILE', TRUE),
    ('portfolio-health', 'READ_FINANCIAL_GOALS', FALSE),
    ('portfolio-health', 'READ_MARKET_DATA', FALSE),
    ('suitability-evaluation', 'READ_MARKET_DATA', TRUE),
    ('suitability-evaluation', 'READ_PORTFOLIO', TRUE),
    ('suitability-evaluation', 'READ_PROFILE', TRUE),
    ('suitability-evaluation', 'RUN_ANALYSIS', TRUE),
    ('suitability-evaluation', 'READ_PUBLIC_RESEARCH', FALSE),
    ('forecast', 'READ_PUBLIC_RESEARCH', TRUE);

INSERT INTO registry.bdlh_runtime_skill_capability(skill_id, capability_name, required) VALUES
    ('stock-research', 'market.resolve_instrument', TRUE),
    ('stock-research', 'market.get_realtime_quote', TRUE),
    ('stock-research', 'market.get_historical_prices', TRUE),
    ('stock-research', 'market.get_financial_statements', TRUE),
    ('stock-research', 'market.get_valuation', TRUE),
    ('stock-research', 'market.get_industry_context', TRUE),
    ('stock-research', 'market.get_money_flow', TRUE),
    ('stock-research', 'market.get_news', TRUE),
    ('stock-research', 'analysis.run_analysis', TRUE),
    ('stock-research', 'research.web_search', FALSE),
    ('stock-research', 'research.deep_search', FALSE),
    ('portfolio-health', 'portfolio.get_current_positions', TRUE),
    ('portfolio-health', 'portfolio.get_account_snapshot', TRUE),
    ('portfolio-health', 'portfolio.build_current_valuation', TRUE),
    ('portfolio-health', 'user.get_risk_profile', TRUE),
    ('suitability-evaluation', 'market.resolve_instrument', TRUE),
    ('suitability-evaluation', 'market.get_realtime_quote', TRUE),
    ('suitability-evaluation', 'market.get_financial_statements', TRUE),
    ('suitability-evaluation', 'market.get_valuation', TRUE),
    ('suitability-evaluation', 'analysis.run_analysis', TRUE),
    ('suitability-evaluation', 'research.web_search', FALSE),
    ('suitability-evaluation', 'research.deep_search', FALSE),
    ('suitability-evaluation', 'portfolio.get_current_positions', TRUE),
    ('suitability-evaluation', 'portfolio.get_account_snapshot', TRUE),
    ('suitability-evaluation', 'portfolio.build_current_valuation', TRUE),
    ('suitability-evaluation', 'user.get_risk_profile', TRUE);
