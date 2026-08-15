package com.bdlh.runtime.agent.react;

/**
 * 统一描述一次有界 ReAct 执行停止的原因，便于前端提示、运行审计和离线统计。
 */
public enum ReactTerminationReason {
    FINAL_ANSWER,
    ASK_USER,
    ACTION_PLAN_COMPLETED,
    MAX_STEPS_REACHED,
    TOOL_BUDGET_EXCEEDED,
    DEADLINE_EXCEEDED,
    DUPLICATE_ACTION_BLOCKED,
    TOOL_TIMEOUT,
    TOOL_FAILED,
    SYSTEM_BUSY,
    POLICY_REJECTED,
    EVIDENCE_INSUFFICIENT,
    MODEL_GATE_BLOCKED
}
