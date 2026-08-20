-- PLATFORM-P1 PostgreSQL bootstrap. Run once with a PostgreSQL administrator:
-- psql -v ON_ERROR_STOP=1 -v runtime_data_password='...' -v memory_service_password='...' \
--   -v checkpoint_password='...' -d bdlhRuntime -f db/platform/bootstrap/001_postgres_roles_and_schemas.sql
--
-- Deliberately do not revoke public permissions or move public tables here. That
-- is P2 cutover work and would break the current Python Stores before replacement.

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
\if :{?checkpoint_password}
\else
  \echo 'checkpoint_password is required'
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
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
              'bdlh_orchestrator_checkpoint', :'checkpoint_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bdlh_orchestrator_checkpoint')
\gexec

ALTER ROLE bdlh_runtime_data PASSWORD :'runtime_data_password';
ALTER ROLE bdlh_memory_service PASSWORD :'memory_service_password';
ALTER ROLE bdlh_orchestrator_checkpoint PASSWORD :'checkpoint_password';

CREATE SCHEMA IF NOT EXISTS business AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS runtime AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS registry AUTHORIZATION bdlh_runtime_data;
CREATE SCHEMA IF NOT EXISTS memory AUTHORIZATION bdlh_memory_service;
CREATE SCHEMA IF NOT EXISTS checkpoint AUTHORIZATION bdlh_orchestrator_checkpoint;

REVOKE ALL ON SCHEMA business, runtime, registry, memory, checkpoint FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA business, runtime, registry TO bdlh_runtime_data;
GRANT USAGE, CREATE ON SCHEMA memory TO bdlh_memory_service;
GRANT USAGE, CREATE ON SCHEMA checkpoint TO bdlh_orchestrator_checkpoint;
