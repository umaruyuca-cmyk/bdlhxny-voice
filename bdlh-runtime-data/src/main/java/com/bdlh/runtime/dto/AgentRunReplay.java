package com.bdlh.runtime.dto;

import com.bdlh.runtime.entity.AgentRun;
import com.bdlh.runtime.entity.AgentStep;
import com.bdlh.runtime.entity.ToolExecution;

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
