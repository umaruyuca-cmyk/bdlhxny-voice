-- 20260826-write-confirmations.sql
-- 混合路线阶段 B4:写操作确认记录表
--
-- 引擎侧 ConfirmationsStore 为内存实现(测试/实验);生产需要跨进程校验时
-- 使用本表持久化。确认记录与「运行 + 工具 + 规范化参数」三元组绑定,
-- 单次消费(status GRANTED → USED),过期/参数变化/跨运行复用均拒绝。
--
-- 数据处理方式:纯新增表,不修改任何既有表与历史数据。
-- 停机要求:不需要停止服务;建议低峰执行并先备份。
-- 幂等:CREATE TABLE IF NOT EXISTS;可安全重跑。
-- 本脚本由维护者手动执行,应用启动、容器启动与测试不会自动执行迁移。

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

CREATE TABLE IF NOT EXISTS touchstone.write_confirmations (
    id                VARCHAR(50) PRIMARY KEY,          -- confirmation_id(cfm-<hex12>)
    run_id            VARCHAR(100) NOT NULL,             -- 绑定的运行标识
    tool_name         VARCHAR(100) NOT NULL,             -- 绑定的工具名
    arguments_hash    VARCHAR(64)  NOT NULL,             -- 规范化参数 SHA-256(键排序+紧凑JSON)
    actor             VARCHAR(100) NOT NULL,             -- 授予者(所有者/实验框架标识)
    expires_at        TIMESTAMPTZ  NOT NULL,             -- 过期时间
    status            VARCHAR(20)  NOT NULL DEFAULT 'GRANTED',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    consumed_at       TIMESTAMPTZ,
    CONSTRAINT write_confirmation_status_valid CHECK (status IN ('GRANTED', 'USED', 'REVOKED')),
    CONSTRAINT write_confirmation_binding_valid CHECK (
        (status = 'USED' AND consumed_at IS NOT NULL)
        OR (status IN ('GRANTED', 'REVOKED') AND consumed_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_write_confirmations_run
    ON touchstone.write_confirmations(run_id, tool_name);
CREATE INDEX IF NOT EXISTS idx_write_confirmations_expiry
    ON touchstone.write_confirmations(expires_at);

COMMENT ON TABLE touchstone.write_confirmations IS
    '写操作确认记录(B4):与 run/tool/规范化参数绑定,单次消费;有效确认只允许对应 Mock 写调用继续';
COMMENT ON COLUMN touchstone.write_confirmations.arguments_hash IS
    '规范化参数哈希(键排序+紧凑JSON 的 SHA-256);参数变化后旧确认失效(CONFIRMATION_ARGUMENTS_MISMATCH)';

INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260826-write-confirmations.sql', '写操作确认记录表 write_confirmations(运行/工具/参数绑定,单次消费)')
ON CONFLICT DO NOTHING;

COMMIT;

-- 核验 SQL(维护者执行后手动验证,不自动运行):
--   1) 表已建:
--      SELECT to_regclass('touchstone.write_confirmations');
--   2) 单次消费约束生效(手工插入样例后验证,验证完删除;md5 仅为冒烟,
--      生产写入由引擎计算的 sha256 十六进制串):
--      INSERT INTO touchstone.write_confirmations
--        (id, run_id, tool_name, arguments_hash, actor, expires_at)
--      VALUES ('cfm-smoke', 'run-smoke', 'mail.send',
--              md5('{}'::text), 'maintainer', now() + interval '5 min');
--      UPDATE touchstone.write_confirmations
--        SET status='USED', consumed_at=now() WHERE id='cfm-smoke';
--      DELETE FROM touchstone.write_confirmations WHERE id='cfm-smoke';
