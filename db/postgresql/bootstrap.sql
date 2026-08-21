-- =============================================================================
-- bootstrap.sql
-- PostgreSQL 平台初始化：角色 + Schema（不含业务表）。
-- 单超管运维也可执行本文件，保证 schema 与角色对象齐全。
--
-- 示例：
--   psql -v ON_ERROR_STOP=1 \
--     -v runtime_data_password='...' \
--     -v memory_service_password='...' \
--     -d <库名> -f db/postgresql/bootstrap.sql
-- =============================================================================

\if :{?runtime_data_password}
\else
  \echo 'runtime_data_password is required'
  \quit
\endif
\if :{?memory_service_password}
\else
  \echo 'memory_service_password is required'
  \quit
\endif

-- 应用侧角色（可选使用；单超管跑 schema 时仍建议创建）
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
              'bdlh_runtime_data', :'runtime_data_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bdlh_runtime_data')
\gexec
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
              'bdlh_memory_service', :'memory_service_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bdlh_memory_service')
\gexec

ALTER ROLE bdlh_runtime_data PASSWORD :'runtime_data_password';
ALTER ROLE bdlh_memory_service PASSWORD :'memory_service_password';

-- business : 业务扩展预留
-- runtime  : Chat/Run/Task/Outbox/通知等运行态
-- registry : Capability Registry 目录
-- memory   : Memory Service
CREATE SCHEMA IF NOT EXISTS business AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS runtime AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS registry AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS memory AUTHORIZATION bdlh_memory_service;

COMMENT ON SCHEMA business IS '业务扩展预留 schema';
COMMENT ON SCHEMA runtime IS '运行态：会话、Run、任务、Outbox、通知投影';
COMMENT ON SCHEMA registry IS 'Capability Registry 目录真源';
COMMENT ON SCHEMA memory IS 'Memory Service 专用 schema';

REVOKE ALL ON SCHEMA business, runtime, registry, memory FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA business, runtime, registry TO bdlh_runtime_data;
GRANT USAGE, CREATE ON SCHEMA memory TO bdlh_memory_service;
