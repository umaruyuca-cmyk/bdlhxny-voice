package com.stockwise.dto;

import com.stockwise.entity.AgentRun;
import com.stockwise.entity.AgentStep;
import com.stockwise.entity.ToolExecution;

import java.util.List;

/**
 * Agent Run 回放视图，按顺序返回运行主体、步骤和工具执行明细。
 */
public record AgentRunReplay(
        AgentRun run,
        List<AgentStep> steps,
        List<ToolExecution> toolExecutions
) {
}
