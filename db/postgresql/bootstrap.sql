-- 新项目 PostgreSQL 平台初始化。必须由数据库管理员手工执行一次：
-- psql -v ON_ERROR_STOP=1 -v runtime_data_password='...' -v memory_service_password='...' \
--   -d bdlhRuntime -f db/postgresql/bootstrap.sql
--
-- 本文件只创建角色和 Schema，不修改 public Schema 的对象或权限。

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

CREATE SCHEMA IF NOT EXISTS business AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS runtime AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS registry AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS memory AUTHORIZATION bdlh_memory_service;

REVOKE ALL ON SCHEMA business, runtime, registry, memory FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA business, runtime, registry TO bdlh_runtime_data;
GRANT USAGE, CREATE ON SCHEMA memory TO bdlh_memory_service;
