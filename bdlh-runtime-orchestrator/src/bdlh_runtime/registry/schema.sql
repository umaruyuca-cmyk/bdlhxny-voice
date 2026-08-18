-- bdlh_runtime/registry/schema.sql —— 资格与工具目录真源（重写 §3.2）
-- 幂等：IF NOT EXISTS；与 db/migrations/20260816_registry_menu.sql 内容一致，
-- 单一真源以本文件为准。测试无 PG 时用 InMemoryRegistryStore，不走本文件。

CREATE TABLE IF NOT EXISTS bdlh_runtime_operation (
    code            VARCHAR(64) PRIMARY KEY,  -- READ_MARKET_DATA 等
    description     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_toolset (
    name            VARCHAR(64) PRIMARY KEY,  -- market_read
    description     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_capability (
    name            VARCHAR(128) PRIMARY KEY, -- market.get_realtime_quote
    description     TEXT NOT NULL,
    domain          VARCHAR(32) NOT NULL,
    adapter         VARCHAR(16) NOT NULL,     -- mcp | java | web | local
    read_only       BOOLEAN NOT NULL DEFAULT TRUE,
    requires_authenticated_user BOOLEAN NOT NULL DEFAULT FALSE,
    required_arguments TEXT[] NOT NULL DEFAULT '{}',
    depends_on      TEXT[] NOT NULL DEFAULT '{}',  -- 前置 capability 名
    output_schema   VARCHAR(64) NOT NULL DEFAULT 'Observation',
    timeout_seconds INTEGER NOT NULL DEFAULT 20,
    cost            INTEGER NOT NULL DEFAULT 1,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_capability_operation (
    capability_name VARCHAR(128) NOT NULL REFERENCES bdlh_runtime_capability(name),
    operation_code  VARCHAR(64)  NOT NULL REFERENCES bdlh_runtime_operation(code),
    PRIMARY KEY (capability_name, operation_code)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_capability_toolset (
    capability_name VARCHAR(128) NOT NULL REFERENCES bdlh_runtime_capability(name),
    toolset_name    VARCHAR(64)  NOT NULL REFERENCES bdlh_runtime_toolset(name),
    PRIMARY KEY (capability_name, toolset_name)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_skill (
    skill_id        VARCHAR(64) PRIMARY KEY,
    skill_version   VARCHAR(64) NOT NULL,
    domain          VARCHAR(32) NOT NULL,
    status          VARCHAR(32) NOT NULL,  -- CURRENT | FOUNDATION | EXPERIMENTAL
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    side_effects_empty BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_skill_operation (
    skill_id        VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_skill(skill_id),
    operation_code  VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_operation(code),
    required        BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_id, operation_code)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_skill_capability (
    skill_id          VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_skill(skill_id),
    capability_name   VARCHAR(128) NOT NULL REFERENCES bdlh_runtime_capability(name),
    required          BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_id, capability_name)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_runtime_allowlist (
    runtime_id      VARCHAR(64) NOT NULL DEFAULT 'default',
    operation_code  VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_operation(code),
    PRIMARY KEY (runtime_id, operation_code)
);

-- account_id = '*' 表示产品默认 entitlement
CREATE TABLE IF NOT EXISTS bdlh_runtime_account_entitlement (
    account_id      VARCHAR(64) NOT NULL,
    operation_code  VARCHAR(64) NOT NULL REFERENCES bdlh_runtime_operation(code),
    PRIMARY KEY (account_id, operation_code)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_fastpath_route (
    name            VARCHAR(32) PRIMARY KEY,  -- chitchat | knowledge | forbidden
    score_threshold DOUBLE PRECISION NOT NULL,
    disposition     VARCHAR(16) NOT NULL,     -- RESPOND | BLOCK
    response        TEXT
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_fastpath_utterance (
    id              BIGSERIAL PRIMARY KEY,
    route_name      VARCHAR(32) NOT NULL REFERENCES bdlh_runtime_fastpath_route(name),
    utterance       TEXT NOT NULL,
    -- 自然键唯一：seed 幂等依赖 ON CONFLICT 命中此约束，否则自增主键每次重启翻倍插入
    CONSTRAINT bdlh_runtime_fastpath_utterance_unique UNIQUE (route_name, utterance)
);

CREATE TABLE IF NOT EXISTS bdlh_runtime_run_budget (
    profile         VARCHAR(64) PRIMARY KEY,  -- default | research
    react_round_limit INTEGER NOT NULL,
    tool_call_limit   INTEGER NOT NULL,
    subgraph_timeout_seconds INTEGER NOT NULL,
    request_timeout_seconds INTEGER NOT NULL
);

-- 数据主题 → 主题能力的对照（GoalCoverage 回填用）。映射到具体 capability，
-- 不映射 toolset 整组（money_flow 若映射 market_read 整组，quote 成功会顶替资金流覆盖）。
CREATE TABLE IF NOT EXISTS bdlh_runtime_topic_capability (
    topic           VARCHAR(32)  NOT NULL,    -- news | money_flow | industry | web_research
    capability_name VARCHAR(128) NOT NULL REFERENCES bdlh_runtime_capability(name),
    PRIMARY KEY (topic, capability_name)
);
