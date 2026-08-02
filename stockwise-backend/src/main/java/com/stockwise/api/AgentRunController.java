package com.stockwise.api;

import com.stockwise.dto.AgentRunReplay;
import com.stockwise.dto.AgentSkillResults;
import com.stockwise.entity.AgentRun;
import com.stockwise.security.SingleUserContext;
import com.stockwise.service.AgentRunService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.NoSuchElementException;
import java.util.UUID;

/**
 * Agent Run 查询接口，支持按用户列出最近运行并按 Run ID 回放审计链路。
 */
@RestController
@RequestMapping("/api/v1/agent-runs")
public class AgentRunController {

    private final AgentRunService agentRunService;
    private final SingleUserContext singleUserContext;

    public AgentRunController(AgentRunService agentRunService, SingleUserContext singleUserContext) {
        this.agentRunService = agentRunService;
        this.singleUserContext = singleUserContext;
    }

    /**
     * 查询用户最近的运行记录，限制最大返回数量以保护数据库。
     */
    @GetMapping
    public List<AgentRun> list(@RequestParam(defaultValue = "20") int limit) {
        // 1. 运行审计包含用户问题和模型输出，游客不能读取固定单用户的历史记录。
        return agentRunService.listRecent(singleUserContext.requirePermission("AGENT_RUN_READ"), limit);
    }

    /**
     * 回放指定 Run 的有序 Action、Observation、策略拒绝与最终回答。
     */
    @GetMapping("/{runId}")
    public AgentRunReplay replay(@PathVariable UUID runId) {
        try {
            return agentRunService.replay(runId, singleUserContext.requirePermission("AGENT_RUN_READ"));
        } catch (NoSuchElementException e) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, e.getMessage(), e);
        } catch (SecurityException e) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, e.getMessage(), e);
        }
    }

    /**
     * 返回本轮可视化所需的结构化 Skill 结果，不暴露完整运行审计细节。
     */
    @GetMapping("/{runId}/skill-results")
    public AgentSkillResults skillResults(@PathVariable UUID runId) {
        try {
            return agentRunService.skillResults(runId, singleUserContext.requirePermission("AGENT_RUN_READ"));
        } catch (NoSuchElementException e) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, e.getMessage(), e);
        } catch (SecurityException e) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, e.getMessage(), e);
        }
    }
}
