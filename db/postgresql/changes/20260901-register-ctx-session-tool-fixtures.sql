-- ══════════════════════════════════════════════════════════════════════
-- 注册 ctx-session-* 用例冻结工具集(gold runtime_mock_fixtures 入库)
--
-- 背景:context-batches 通道按用例 fixture_set_id 取冻结集(variants.json
-- common_conditions 声明);此前仅有全局 ab-eval(无 file.read/code.read),
-- ctx-session 用例工具观测全部命中失败桩。本脚本把三个用例 gold 的
-- runtime_mock_fixtures(判官方文件,本就供 Mock 使用,按 path 冻结)注册为
-- DB 冻结集,经 data 服务 /tool-fixtures 消费。
--
-- call_key 约定:覆盖键「工具名:path」(engine FrozenObservations 按
-- symbol→path→基准依次查找);不注册基准键行——脚本外调用未命中失败桩
-- 是冻结纪律。response_status 统一大写(与 seed 08 一致)。
-- arguments_hash/response_hash 为 NOT NULL:沿 20260822-fixture-deep-search
-- 的放开→INSERT→回填→恢复模式。
--
-- 执行:psql <连接串> -v ON_ERROR_STOP=1 -f 20260901-register-ctx-session-tool-fixtures.sql
-- 幂等:全部 INSERT 带 ON CONFLICT DO NOTHING,可安全重跑。
-- 再生成:engine/.venv/Scripts/python engine/scripts/register_ctx_session_tool_fixtures.py
-- ══════════════════════════════════════════════════════════════════════

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── 1. 冻结集定义 ──────────────────────────────────────────────────────

INSERT INTO touchstone.fixture_sets
    (id, version, title, fixture_type, source_hash, public)
VALUES
('ctx-session-database-deploy-01-tools-v1', 1, $fx$"ctx-session-database-deploy-01 冻结工具返回(按 path,源 gold runtime_mock_fixtures)"$fx$, 'STATIC', '1f4cb0a23dc2176a8b2bb2493effd1e2ea115ee4454bd16931522511ad33f99a', false),
('ctx-session-product-evolution-01-tools-v1', 1, $fx$"ctx-session-product-evolution-01 冻结工具返回(按 path,源 gold runtime_mock_fixtures)"$fx$, 'STATIC', 'f034ded344dfcc431da8ad2ad76339e01800005d17074498cdce4692d86a676b', false),
('ctx-session-context-engine-debug-01-tools-v1', 1, $fx$"ctx-session-context-engine-debug-01 冻结工具返回(按 path,源 gold runtime_mock_fixtures)"$fx$, 'STATIC', '0e26f9cf72d0ac2539d1c8b0e50baf9f682c59250d6bd203b03ade9951676bdd', false)
ON CONFLICT (id, version) DO NOTHING;

-- ── 2. 冻结返回(按 path 覆盖键) ──────────────────────────────────────

ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN arguments_hash DROP NOT NULL;
ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN response_hash DROP NOT NULL;

INSERT INTO touchstone.fixture_tool_responses
    (fixture_set_id, fixture_set_version, call_key, tool_name, arguments,
     response_status, response, observed_at, simulated_latency_ms, sequence)
VALUES
('ctx-session-database-deploy-01-tools-v1', 1, 'file.read:db/postgresql/setup/init.sql', 'file.read', $fx${"path":"db/postgresql/setup/init.sql"}$fx$, 'SUCCESS', $fx${"path":"db/postgresql/setup/init.sql","content_excerpt":"读取路径: db/postgresql/setup/init.sql\n冻结范围: 第 1-520 行，共 1155 行\n…","content_hash":"sha256:bdae06f8a1bf0f73268135f243433c93f51695cb4e78d93bdf36ce1e9261e4d2","line_range":"1-60","simulated":true}$fx$, NULL, 0, 1),
('ctx-session-database-deploy-01-tools-v1', 1, 'code.read:data/src/main/java/com/bdlh/touchstone/data/repository/RunRepository.java', 'code.read', $fx${"path":"data/src/main/java/com/bdlh/touchstone/data/repository/RunRepository.java"}$fx$, 'SUCCESS', $fx${"path":"data/src/main/java/com/bdlh/touchstone/data/repository/RunRepository.java","content_excerpt":"读取路径: data/src/main/java/com/bdlh/touchstone/data/repository…","content_hash":"sha256:617b377f3729c4741ca1506a015bc12c2ccb589f45db728039954554ff91d3fb","line_range":"1-60","simulated":true}$fx$, NULL, 0, 2),
('ctx-session-database-deploy-01-tools-v1', 1, 'file.read:deploy/docker-compose.yml', 'file.read', $fx${"path":"deploy/docker-compose.yml"}$fx$, 'SUCCESS', $fx${"path":"deploy/docker-compose.yml","content_excerpt":"读取路径: deploy/docker-compose.yml\n冻结范围: 第 1-81 行，共 81 行\n----- …","content_hash":"sha256:4856f508a299502c19509f055bebcd02fd72e092f10d7810291b24d86ca6e9bb","line_range":"1-60","simulated":true}$fx$, NULL, 0, 3),
('ctx-session-database-deploy-01-tools-v1', 1, 'file.read:deploy/docker-compose.cloud.yml', 'file.read', $fx${"path":"deploy/docker-compose.cloud.yml"}$fx$, 'SUCCESS', $fx${"path":"deploy/docker-compose.cloud.yml","content_excerpt":"读取路径: deploy/docker-compose.cloud.yml\n冻结范围: 第 1-60 行，共 60 行\n…","content_hash":"sha256:e0b0e1b7208306d0cb329ec6a38e865b8267611ed25158cc8c00b09d77a3d393","line_range":"1-60","simulated":true}$fx$, NULL, 0, 4),
('ctx-session-product-evolution-01-tools-v1', 1, 'file.read:docs/product/产品目标与使用方式.md', 'file.read', $fx${"path":"docs/product/产品目标与使用方式.md"}$fx$, 'SUCCESS', $fx${"path":"docs/product/产品目标与使用方式.md","content_excerpt":"读取路径: docs/product/产品目标与使用方式.md\n冻结范围: 第 1-168 行，共 168 行\n----…","content_hash":"sha256:7e5a125ec08745f58a6f1eea1020caf278ae0364a18ec99150a041eaf10c2527","line_range":"1-60","simulated":true}$fx$, NULL, 0, 1),
('ctx-session-product-evolution-01-tools-v1', 1, 'file.read:docs/context/长上下文构建与压缩.md', 'file.read', $fx${"path":"docs/context/长上下文构建与压缩.md"}$fx$, 'SUCCESS', $fx${"path":"docs/context/长上下文构建与压缩.md","content_excerpt":"读取路径: docs/context/长上下文构建与压缩.md\n冻结范围: 第 1-401 行，共 401 行\n----…","content_hash":"sha256:22b3da256f926b6beb83485e34b65d1a77da090713697bbcfa94f3b3ebef3619","line_range":"1-60","simulated":true}$fx$, NULL, 0, 2),
('ctx-session-product-evolution-01-tools-v1', 1, 'file.read:web/scripts/generate-context-library.mjs', 'file.read', $fx${"path":"web/scripts/generate-context-library.mjs"}$fx$, 'SUCCESS', $fx${"path":"web/scripts/generate-context-library.mjs","content_excerpt":"读取路径: web/scripts/generate-context-library.mjs\n冻结范围: 第 1-179…","content_hash":"sha256:7c3c30c252dac660925762e623816906bb209f4d0d90f46ee5b3aeb43df936f6","line_range":"1-60","simulated":true}$fx$, NULL, 0, 3),
('ctx-session-context-engine-debug-01-tools-v1', 1, 'code.read:engine/src/bdlh_runtime/session/compiler.py', 'code.read', $fx${"path":"engine/src/bdlh_runtime/session/compiler.py"}$fx$, 'SUCCESS', $fx${"path":"engine/src/bdlh_runtime/session/compiler.py","content_excerpt":"读取路径: engine/src/bdlh_runtime/session/compiler.py\n冻结范围: 第 1-…","content_hash":"sha256:3982396da000bd823037e63c073bf56afc143d7b9624f91315b2661cc4ee3d28","line_range":"1-60","simulated":true}$fx$, NULL, 0, 1),
('ctx-session-context-engine-debug-01-tools-v1', 1, 'code.read:engine/src/bdlh_runtime/context/builder.py', 'code.read', $fx${"path":"engine/src/bdlh_runtime/context/builder.py"}$fx$, 'SUCCESS', $fx${"path":"engine/src/bdlh_runtime/context/builder.py","content_excerpt":"读取路径: engine/src/bdlh_runtime/context/builder.py\n冻结范围: 第 1-5…","content_hash":"sha256:679d2ba679349c59165e376795c57e2ad1f927702b0c7b6f7fd5ec7f34485e37","line_range":"1-60","simulated":true}$fx$, NULL, 0, 2),
('ctx-session-context-engine-debug-01-tools-v1', 1, 'code.read:engine/src/bdlh_runtime/engine/loop.py', 'code.read', $fx${"path":"engine/src/bdlh_runtime/engine/loop.py"}$fx$, 'SUCCESS', $fx${"path":"engine/src/bdlh_runtime/engine/loop.py","content_excerpt":"读取路径: engine/src/bdlh_runtime/engine/loop.py\n冻结范围: 第 1-620 行…","content_hash":"sha256:eeb8d61a4eb9cdffcdef8e09fdb1f590f225f70632ab07942dd380fb3ce326f0","line_range":"1-60","simulated":true}$fx$, NULL, 0, 3)
ON CONFLICT (fixture_set_id, fixture_set_version, call_key) DO NOTHING;

UPDATE touchstone.fixture_tool_responses
SET arguments_hash = 'sha256:' || encode(digest(arguments::text, 'sha256'), 'hex'),
    response_hash  = 'sha256:' || encode(digest(response::text, 'sha256'), 'hex')
WHERE fixture_set_id IN ('ctx-session-database-deploy-01-tools-v1', 'ctx-session-product-evolution-01-tools-v1', 'ctx-session-context-engine-debug-01-tools-v1')
  AND arguments_hash IS NULL;

ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN arguments_hash SET NOT NULL;
ALTER TABLE touchstone.fixture_tool_responses ALTER COLUMN response_hash SET NOT NULL;

INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260901-register-ctx-session-tool-fixtures.sql',
        '注册 ctx-session-* 三套用例冻结工具集(gold runtime_mock_fixtures 按 path 覆盖键入库,供 context-batches 通道按用例取集)')
ON CONFLICT DO NOTHING;

COMMIT;
