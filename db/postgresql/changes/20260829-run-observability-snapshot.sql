-- 20260829: 运行链路可观测性快照(阶段一:完成后可复查)
-- 背景:此前 model_calls 只保存计量摘要,当轮 Tool Schema、请求参数三态
-- (requested/sent/unsupported)、应用层请求快照均未落库;tool_calls 与发起
-- 它的模型调用、模型生成的 call_id、全局事件序号没有关联列,页面无法重建
-- 「模型 → 工具 → 模型」真实顺序。本脚本补齐快照与关联列,配合 engine 统一
-- recorder 与数据服务 detail API 改造(docs/design/Agent运行链路可观测性优化设计.md)。

-- 模型调用快照列
ALTER TABLE touchstone.model_calls
    ADD COLUMN IF NOT EXISTS request_snapshot_version INTEGER,
    ADD COLUMN IF NOT EXISTS request_payload JSONB,
    ADD COLUMN IF NOT EXISTS tool_schemas JSONB,
    ADD COLUMN IF NOT EXISTS requested_params JSONB,
    ADD COLUMN IF NOT EXISTS sent_params JSONB,
    ADD COLUMN IF NOT EXISTS unsupported_params JSONB,
    ADD COLUMN IF NOT EXISTS decision VARCHAR(20),
    ADD COLUMN IF NOT EXISTS response_summary JSONB;

COMMENT ON COLUMN touchstone.model_calls.request_snapshot_version IS
    '请求快照协议版本(当前 1;request_payload/tool_schemas/参数列的联合协议号)';
COMMENT ON COLUMN touchstone.model_calls.request_payload IS
    '应用层完整请求快照(model/messages/tool_schemas/sent parameters;进入 SDK 前组装,非网络抓包)';
COMMENT ON COLUMN touchstone.model_calls.tool_schemas IS
    '当轮实际绑定给模型的 Tool Schema(search 提供方式下逐轮不同;不以最终 visible_tools 代替历史轮次)';
COMMENT ON COLUMN touchstone.model_calls.requested_params IS
    '模板或用户请求的参数值(四态口径:requested)';
COMMENT ON COLUMN touchstone.model_calls.sent_params IS
    '应用实际交给 SDK 的参数值(四态口径:sent;不得用 effective 冒充)';
COMMENT ON COLUMN touchstone.model_calls.unsupported_params IS
    '未发送字段及原因(四态口径:unsupported)';
COMMENT ON COLUMN touchstone.model_calls.decision IS
    '模型可观察决策:call_tool / answer';
COMMENT ON COLUMN touchstone.model_calls.response_summary IS
    '可观察模型输出摘要(决策 + Tool Call 摘要 + 文本截断,不含隐藏思维)';

-- 工具调用关联列
ALTER TABLE touchstone.tool_calls
    ADD COLUMN IF NOT EXISTS call_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS requested_event_sequence INTEGER,
    ADD COLUMN IF NOT EXISTS completed_event_sequence INTEGER;

COMMENT ON COLUMN touchstone.tool_calls.call_id IS
    '模型生成的工具调用 id(与 ToolMessage.tool_call_id 对应,按名称 FIFO 与模型调用配对)';
COMMENT ON COLUMN touchstone.tool_calls.requested_event_sequence IS
    'tool.requested 事件的 run_events.sequence(全局时间线定位)';
COMMENT ON COLUMN touchstone.tool_calls.completed_event_sequence IS
    'tool.completed 事件的 run_events.sequence(全局时间线定位)';

-- 索引:明细页按发起模型调用取工具调用
CREATE INDEX IF NOT EXISTS idx_tool_calls_model_call
    ON touchstone.tool_calls (model_call_id)
    WHERE model_call_id IS NOT NULL;
