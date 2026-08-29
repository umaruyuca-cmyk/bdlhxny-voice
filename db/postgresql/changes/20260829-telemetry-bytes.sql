-- 20260829: 遥测存储量计量(可观测性设计 §9.3/§10 阶段三)
-- 背景:明细表(events/model_calls/tool_calls/guardrail_checks)体量此前不可见,
-- 无法监控存储增长。engine 落库明细时按 canonical JSON 字节数汇总写入本列;
-- 批次级合计由检索接口 SUM 提供。

ALTER TABLE touchstone.run_measurements
    ADD COLUMN IF NOT EXISTS telemetry_bytes BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN touchstone.run_measurements.telemetry_bytes IS
    '本运行遥测明细(events/model_calls/tool_calls/guardrail_checks)的 canonical JSON 字节总量,engine 落库时计算';
