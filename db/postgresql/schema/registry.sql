-- =============================================================================
-- registry.sql
-- Capability Registry 最终八张目录表（数据库唯一真源）。
-- 资格上限 / entitlement / 预算 / 快路径不在本 schema，见 Orchestrator 配置与 fastpath_data。
-- =============================================================================

-- 1) Operation：产品授予的能力资格码
CREATE TABLE registry.bdlh_runtime_operation (
    code VARCHAR(64) PRIMARY KEY,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE registry.bdlh_runtime_operation IS 'Operation 目录：产品授予的能力资格码';
COMMENT ON COLUMN registry.bdlh_runtime_operation.code IS '资格码，如 READ_MARKET_DATA';
COMMENT ON COLUMN registry.bdlh_runtime_operation.description IS '资格说明';
COMMENT ON COLUMN registry.bdlh_runtime_operation.created_at IS '创建时间';

-- 2) Toolset：能力业务分组（派生视图用，不单独授权）
CREATE TABLE registry.bdlh_runtime_toolset (
    name VARCHAR(64) PRIMARY KEY,
    description TEXT NOT NULL
);

COMMENT ON TABLE registry.bdlh_runtime_toolset IS 'Toolset 目录：能力业务分组名';
COMMENT ON COLUMN registry.bdlh_runtime_toolset.name IS '分组名，如 market_read';
COMMENT ON COLUMN registry.bdlh_runtime_toolset.description IS '分组说明';

-- 3) Capability：可执行能力
CREATE TABLE registry.bdlh_runtime_capability (
    name VARCHAR(128) PRIMARY KEY,
    description TEXT NOT NULL,
    domain VARCHAR(32) NOT NULL,
    adapter VARCHAR(16) NOT NULL,
    read_only BOOLEAN NOT NULL DEFAULT TRUE,
    requires_authenticated_user BOOLEAN NOT NULL DEFAULT FALSE,
    required_arguments TEXT[] NOT NULL DEFAULT '{}',
    depends_on TEXT[] NOT NULL DEFAULT '{}',
    timeout_seconds INTEGER NOT NULL DEFAULT 20,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE registry.bdlh_runtime_capability IS 'Capability 目录：可调用的统一能力';
COMMENT ON COLUMN registry.bdlh_runtime_capability.name IS '能力名，如 market.get_realtime_quote';
COMMENT ON COLUMN registry.bdlh_runtime_capability.description IS '能力说明（可进 Agent 菜单）';
COMMENT ON COLUMN registry.bdlh_runtime_capability.domain IS '能力域标签，如 market/portfolio/research';
COMMENT ON COLUMN registry.bdlh_runtime_capability.adapter IS '适配器类型：mcp | java | web | local';
COMMENT ON COLUMN registry.bdlh_runtime_capability.read_only IS '是否只读；v1 启用能力必须为 TRUE';
COMMENT ON COLUMN registry.bdlh_runtime_capability.requires_authenticated_user IS '进入 allowed 是否要求已登录用户';
COMMENT ON COLUMN registry.bdlh_runtime_capability.required_arguments IS '调用必填参数名数组';
COMMENT ON COLUMN registry.bdlh_runtime_capability.depends_on IS '依赖的其他 capability 名数组（闭包补齐）';
COMMENT ON COLUMN registry.bdlh_runtime_capability.timeout_seconds IS '建议超时秒数';
COMMENT ON COLUMN registry.bdlh_runtime_capability.enabled IS '是否启用；FALSE 不得进入 eligible';

-- 4) Capability ↔ Operation
CREATE TABLE registry.bdlh_runtime_capability_operation (
    capability_name VARCHAR(128) NOT NULL REFERENCES registry.bdlh_runtime_capability(name),
    operation_code VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_operation(code),
    PRIMARY KEY (capability_name, operation_code)
);

COMMENT ON TABLE registry.bdlh_runtime_capability_operation IS 'Capability 所需 Operation 关联';
COMMENT ON COLUMN registry.bdlh_runtime_capability_operation.capability_name IS '能力名';
COMMENT ON COLUMN registry.bdlh_runtime_capability_operation.operation_code IS '所需资格码';

-- 5) Capability ↔ Toolset
CREATE TABLE registry.bdlh_runtime_capability_toolset (
    capability_name VARCHAR(128) NOT NULL REFERENCES registry.bdlh_runtime_capability(name),
    toolset_name VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_toolset(name),
    PRIMARY KEY (capability_name, toolset_name)
);

COMMENT ON TABLE registry.bdlh_runtime_capability_toolset IS 'Capability 所属 Toolset 关联';
COMMENT ON COLUMN registry.bdlh_runtime_capability_toolset.capability_name IS '能力名';
COMMENT ON COLUMN registry.bdlh_runtime_capability_toolset.toolset_name IS '工具集名';

-- 6) Skill：产品技能包
CREATE TABLE registry.bdlh_runtime_skill (
    skill_id VARCHAR(64) PRIMARY KEY,
    skill_version VARCHAR(64) NOT NULL,
    domain VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE registry.bdlh_runtime_skill IS 'Skill 目录：产品技能包声明';
COMMENT ON COLUMN registry.bdlh_runtime_skill.skill_id IS '技能 ID，如 stock-research';
COMMENT ON COLUMN registry.bdlh_runtime_skill.skill_version IS '技能版本号';
COMMENT ON COLUMN registry.bdlh_runtime_skill.domain IS '所属 Domain，如 finance';
COMMENT ON COLUMN registry.bdlh_runtime_skill.status IS '成熟度：CURRENT | FOUNDATION | EXPERIMENTAL';
COMMENT ON COLUMN registry.bdlh_runtime_skill.enabled IS '是否启用；仅启用 Skill 参与资格菜单';

-- 7) Skill ↔ Operation
CREATE TABLE registry.bdlh_runtime_skill_operation (
    skill_id VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_skill(skill_id),
    operation_code VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_operation(code),
    required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_id, operation_code)
);

COMMENT ON TABLE registry.bdlh_runtime_skill_operation IS 'Skill 声明的 Operation（required=false 为可选资格）';
COMMENT ON COLUMN registry.bdlh_runtime_skill_operation.skill_id IS '技能 ID';
COMMENT ON COLUMN registry.bdlh_runtime_skill_operation.operation_code IS '资格码';
COMMENT ON COLUMN registry.bdlh_runtime_skill_operation.required IS 'TRUE=必选资格；FALSE=可选（仍并入 effective_operations）';

-- 8) Skill ↔ Capability
CREATE TABLE registry.bdlh_runtime_skill_capability (
    skill_id VARCHAR(64) NOT NULL REFERENCES registry.bdlh_runtime_skill(skill_id),
    capability_name VARCHAR(128) NOT NULL REFERENCES registry.bdlh_runtime_capability(name),
    required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (skill_id, capability_name)
);

COMMENT ON TABLE registry.bdlh_runtime_skill_capability IS 'Skill 声明的 Capability（required=false 为可选能力）';
COMMENT ON COLUMN registry.bdlh_runtime_skill_capability.skill_id IS '技能 ID';
COMMENT ON COLUMN registry.bdlh_runtime_skill_capability.capability_name IS '能力名';
COMMENT ON COLUMN registry.bdlh_runtime_skill_capability.required IS 'TRUE=技能核心能力；FALSE=可选能力';
