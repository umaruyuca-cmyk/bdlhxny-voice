-- 20260830-context-analysis-jobs.sql
-- 上下文工作台 P2 定时分析任务的两张结果表:
--   1. context_segment_quality_checks:摘要段语义质量抽检结果
--      (评审模型对比摘要与来源原文;verdict 含 ERROR=评审调用失败,不伪造通过);
--   2. context_analysis_runs:每次分析运行(定时/手动)的状态与报告
--      (报告 JSON 含阈值分组对照、成本收益、相关性分析)。
--
-- 现有数据处理:纯新增结构,不回填、不修改既有表。
-- 服务影响:只建新表;Data/Engine 可在线执行。
-- 幂等性:CREATE TABLE IF NOT EXISTS + 索引 IF NOT EXISTS + 登记 ON CONFLICT DO NOTHING。

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE IF NOT EXISTS touchstone.context_segment_quality_checks (
    id                    UUID PRIMARY KEY,
    segment_id            VARCHAR(200) NOT NULL,
    session_id            VARCHAR(200) NOT NULL,
    account_id            UUID NOT NULL
                          REFERENCES touchstone.accounts(id) ON DELETE CASCADE,
    verdict               VARCHAR(20) NOT NULL,
    missing_facts         JSONB NOT NULL DEFAULT '[]'::jsonb,
    hallucinations        JSONB NOT NULL DEFAULT '[]'::jsonb,
    judge_model           VARCHAR(200),
    prompt_version        VARCHAR(100) NOT NULL,
    source_hash_at_check  VARCHAR(100) NOT NULL,
    error_code            VARCHAR(100),
    detail                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT segment_quality_verdict_valid
        CHECK (verdict IN ('PASS', 'WARN', 'FAIL', 'ERROR')),
    CONSTRAINT segment_quality_arrays_valid
        CHECK (jsonb_typeof(missing_facts) = 'array' AND jsonb_typeof(hallucinations) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_segment_quality_session_time
    ON touchstone.context_segment_quality_checks (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_segment_quality_segment
    ON touchstone.context_segment_quality_checks (segment_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_segment_quality_account
    ON touchstone.context_segment_quality_checks (account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS touchstone.context_analysis_runs (
    id                UUID PRIMARY KEY,
    status            VARCHAR(20) NOT NULL,
    trigger_source    VARCHAR(20) NOT NULL,
    sampled_segments  INTEGER NOT NULL DEFAULT 0,
    judge_calls       INTEGER NOT NULL DEFAULT 0,
    judge_errors      INTEGER NOT NULL DEFAULT 0,
    report            JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code        VARCHAR(100),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    CONSTRAINT analysis_run_status_valid
        CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    CONSTRAINT analysis_run_trigger_valid
        CHECK (trigger_source IN ('SCHEDULED', 'MANUAL')),
    CONSTRAINT analysis_run_counts_valid
        CHECK (sampled_segments >= 0 AND judge_calls >= 0 AND judge_errors >= 0)
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_time
    ON touchstone.context_analysis_runs (started_at DESC);

INSERT INTO touchstone.database_changes (script_name, description)
VALUES (
    '20260830-context-analysis-jobs.sql',
    'P2 定时分析任务:新增摘要段语义质量抽检结果表 context_segment_quality_checks 与分析运行表 context_analysis_runs'
)
ON CONFLICT (script_name) DO NOTHING;

-- 核验
SELECT to_regclass('touchstone.context_segment_quality_checks') AS checks_table,
       to_regclass('touchstone.context_analysis_runs') AS runs_table;

SELECT script_name, applied_at
FROM touchstone.database_changes
WHERE script_name = '20260830-context-analysis-jobs.sql';

COMMIT;
