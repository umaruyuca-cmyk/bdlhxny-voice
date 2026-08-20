-- Registry 目录的全量建表脚本，由 Java 数据平面所有。

CREATE TABLE registry.bdlh_runtime_operation (
    code VARCHAR(64) PRIMARY KEY,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE registry.bdlh_runtime_toolset (
    name VARCHAR(64) PRIMARY KEY,
    description TEXT NOT NULL
);
CREATE TABLE registry.bdlh_runtime_capability (
    name VARCHAR(128) PRIMARY KEY,
    description TEXT NOT NULL,
    domain VARCHAR(32) NOT NULL,
    adapter VARCHAR(16) NOT NULL,
    read_only BOOLEAN NOT NULL DEFAULT TRUE,
    requires_authenticated_user BOOLEAN NOT NULL DEFAULT FALSE,
    required_arguments TEXT[] NOT NULL DEFAULT '{}',
    depends_on TEXT[] NOT NULL DEFAULT '{}',
    output_schema VARCHAR(64) NOT NULL DEFAULT 'Observation',
    timeout_seconds INTEGER NOT NULL DEFAULT 20,
    cost INTEGER NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE registry.bdlh_runtime_capability_operation (
    capability_name VARCHAR(128) NOT NULL REFERENCES registry.bdlh_runtime_capability(name),
    operation_code VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_operation(code),
    PRIMARY KEY (capability_name, operation_code)
);
CREATE TABLE registry.bdlh_runtime_capability_toolset (
    capability_name VARCHAR(128) NOT NULL REFERENCES registry.bdlh_runtime_capability(name),
    toolset_name VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_toolset(name),
    PRIMARY KEY (capability_name, toolset_name)
);
CREATE TABLE registry.bdlh_runtime_skill (
    skill_id VARCHAR(64) PRIMARY KEY,
    skill_version VARCHAR(64) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    side_effects_empty BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE registry.bdlh_runtime_skill_operation (
    skill_id VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_skill(skill_id),
    operation_code VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_operation(code),
    required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_id, operation_code)
);
CREATE TABLE registry.bdlh_runtime_skill_capability (
    skill_id VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_skill(skill_id),
    capability_name VARCHAR(128) NOT NULL REFERENCES registry.bdlh_runtime_capability(name),
    required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_id, capability_name)
);
CREATE TABLE registry.bdlh_runtime_runtime_allowlist (
    runtime_id VARCHAR(64) NOT NULL DEFAULT 'default',
    operation_code VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_operation(code),
    PRIMARY KEY (runtime_id, operation_code)
);
CREATE TABLE registry.bdlh_runtime_account_entitlement (
    account_id VARCHAR(64) NOT NULL,
    operation_code VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_operation(code),
    PRIMARY KEY (account_id, operation_code)
);
CREATE TABLE registry.bdlh_runtime_fastpath_route (
    name VARCHAR(32) PRIMARY KEY,
    score_threshold DOUBLE PRECISION NOT NULL,
    disposition VARCHAR(16) NOT NULL,
    response TEXT
);
CREATE TABLE registry.bdlh_runtime_fastpath_utterance (
    id BIGSERIAL PRIMARY KEY,
    route_name VARCHAR(32) NOT NULL REFERENCES registry.bdlh_runtime_fastpath_route(name),
    utterance TEXT NOT NULL,
    CONSTRAINT bdlh_runtime_fastpath_utterance_unique UNIQUE (route_name, utterance)
);
CREATE TABLE registry.bdlh_runtime_run_budget (
    profile VARCHAR(64) PRIMARY KEY,
    react_round_limit INTEGER NOT NULL,
    tool_call_limit INTEGER NOT NULL,
    subgraph_timeout_seconds INTEGER NOT NULL,
    request_timeout_seconds INTEGER NOT NULL
);
CREATE TABLE registry.bdlh_runtime_topic_capability (
    topic VARCHAR(32) NOT NULL,
    capability_name VARCHAR(128) NOT NULL REFERENCES registry.bdlh_runtime_capability(name),
    PRIMARY KEY (topic, capability_name)
);
