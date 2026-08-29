-- 20260828: 批次执行报告持久化
-- 背景:批次完成后的执行报告(压缩明细/按变体汇总/统计)此前只存在于 engine 内存作业
-- 与本地工件文件中,服务重启后页面只能回退读盘。本脚本把报告落进数据库,作为报告的
-- 权威持久来源(engine 读报告的顺序:数据库 → 本地工件兜底)。
-- 报告体为执行器完整 payload(JSON,当前量级 50-200KB),与 fixed_conditions 同为 JSONB。

ALTER TABLE touchstone.run_batches
    ADD COLUMN IF NOT EXISTS report JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN touchstone.run_batches.report IS
    '批次执行报告(执行器完整 payload:压缩明细/按变体汇总/统计;完成时由 engine 写入,报告读取的第一来源)';
