package com.bdlh.runtime.api;

import com.bdlh.runtime.dto.AgentRunReplay;
import com.bdlh.runtime.dto.AgentSkillResults;
import com.bdlh.runtime.entity.AgentRun;
import com.bdlh.runtime.security.SingleUserContext;
import com.bdlh.runtime.service.AgentRunService;
import org.springframework.http.HttpStatus;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
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
@ConditionalOnProperty(
        name = "bdlh_runtime.legacy-agent-runtime.enabled",
        havingValue = "true")
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
        // 1. 当前为单用户工作站，运行记录统一归属服务端配置的用户。
        return agentRunService.listRecent(singleUserContext.requireAuthenticatedUserId(), limit);
    }

    /**
     * 回放指定 Run 的有序 Action、Observation、策略拒绝与最终回答。
     */
    @GetMapping("/{runId}")
    public AgentRunReplay replay(@PathVariable UUID runId) {
        try {
            return agentRunService.replay(runId, singleUserContext.requireAuthenticatedUserId());
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
            return agentRunService.skillResults(runId, singleUserContext.requireAuthenticatedUserId());
        } catch (NoSuchElementException e) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, e.getMessage(), e);
        } catch (SecurityException e) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, e.getMessage(), e);
        }
    }
}
