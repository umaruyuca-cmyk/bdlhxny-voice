package com.bdlh.runtime.agent.routing;

import java.util.List;

/**
 * 保存由最终 Route 和主体类型确定的本轮唯一 Action 集合，防止执行层重新猜测意图。
 */
public record ExecutionPlan(List<String> actions) {

    public ExecutionPlan {
        actions = actions == null ? List.of() : List.copyOf(actions);
    }

    /**
     * 判断本轮计划是否允许指定 Action。
     */
    public boolean allows(String action) {
        return actions.contains(action);
    }
}
