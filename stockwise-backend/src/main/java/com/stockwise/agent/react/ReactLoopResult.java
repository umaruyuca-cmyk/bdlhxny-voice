package com.stockwise.agent.react;

import java.util.List;
import java.util.Optional;

/**
 * 汇总有界 ReAct 循环的 Observation、预算消耗与终止原因。
 */
public record ReactLoopResult(
        List<ReactObservation> observations,
        ReactTerminationReason terminationReason,
        int rounds,
        int toolCalls,
        String detail
) {

    public ReactLoopResult {
        observations = observations == null ? List.of() : List.copyOf(observations);
        detail = detail == null ? "" : detail;
    }

    /**
     * 只有动作计划完整执行时才能进入证据校验和最终回答阶段。
     */
    public boolean completed() {
        return terminationReason == ReactTerminationReason.ACTION_PLAN_COMPLETED;
    }

    /**
     * 按工具名读取首次 Observation，防止调用方依赖动作列表下标。
     */
    public Optional<ReactObservation> observation(String toolName) {
        return observations.stream()
                .filter(item -> item.toolName().equals(toolName))
                .findFirst();
    }
}
