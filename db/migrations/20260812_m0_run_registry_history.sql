-- M0: persistent Run Registry and Analysis History for BDLH Agent Runtime.
-- Python Runtime owns these tables. Production must apply this migration (or rely on
-- CREATE TABLE IF NOT EXISTS performed by the Postgres store constructors).

CREATE TABLE IF NOT EXISTS public.bdlh_runtime_run_registry (
    run_id VARCHAR(64) PRIMARY KEY,
    thread_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(64),
    checkpoint_id VARCHAR(255),
    runtime_path VARCHAR(64) NOT NULL DEFAULT 'legacy_root_graph',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_run_registry_thread
    ON public.bdlh_runtime_run_registry(thread_id);

CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_run_registry_user
    ON public.bdlh_runtime_run_registry(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.bdlh_runtime_analysis_history (
    history_id VARCHAR(64) PRIMARY KEY,
    thread_id VARCHAR(255) NOT NULL,
    run_id VARCHAR(64) NOT NULL,
    authenticated_user_id VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bdlh_runtime_analysis_history_thread_user
    ON public.bdlh_runtime_analysis_history(thread_id, authenticated_user_id, created_at);
