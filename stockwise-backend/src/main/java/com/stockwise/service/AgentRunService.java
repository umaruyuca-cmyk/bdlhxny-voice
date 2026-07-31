package com.stockwise.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.agent.AgentRunContext;
import com.stockwise.agent.routing.RouteDecision;
import com.stockwise.dto.AgentRunReplay;
import com.stockwise.entity.AgentRun;
import com.stockwise.entity.AgentStep;
import com.stockwise.entity.ToolExecution;
import com.stockwise.llm.ChatIntent;
import com.stockwise.mapper.AgentRunMapper;
import com.stockwise.mapper.AgentStepMapper;
import com.stockwise.mapper.ToolExecutionMapper;
import com.stockwise.skill.SkillDefinition;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.UUID;
import java.util.function.Supplier;

/**
 * 管理 Agent Run 的审计生命周期，持久化可回放的 Action、Observation 与最终回答。
 * 仅记录业务输入输出和策略决策，不保存模型隐藏思维链。
 */
@Service
public class AgentRunService {

    private static final int DEFAULT_MAX_TOOL_CALLS = 4;
    private static final int MAX_AUDIT_TEXT_LENGTH = 100_000;

    private final AgentRunMapper agentRunMapper;
    private final AgentStepMapper agentStepMapper;
    private final ToolExecutionMapper toolExecutionMapper;
    private final ObjectMapper objectMapper;

    public AgentRunService(AgentRunMapper agentRunMapper,
                           AgentStepMapper agentStepMapper,
                           ToolExecutionMapper toolExecutionMapper,
                           ObjectMapper objectMapper) {
        this.agentRunMapper = agentRunMapper;
        this.agentStepMapper = agentStepMapper;
        this.toolExecutionMapper = toolExecutionMapper;
        this.objectMapper = objectMapper;
    }

    /**
     * 创建一次独立的 Agent Run，使后续步骤拥有稳定的关联标识。
     */
    public AgentRunContext start(Long userId, String sessionId, String request,
                                 ChatIntent intent, SkillDefinition skill) {
        UUID runId = UUID.randomUUID();
        AgentRun run = new AgentRun();
        run.setRunId(runId);
        run.setUserId(userId);
        run.setSessionId(sessionId);
        run.setIntent(intent == null ? null : intent.name());
        run.setSkillName(skill.name());
        run.setSkillVersion(skill.version());
        run.setStatus("running");
        run.setRequestText(request);
        int maxToolCalls = intConstraint(skill, "maxToolCalls", DEFAULT_MAX_TOOL_CALLS);
        run.setMaxToolCalls(maxToolCalls);
        run.setToolCallCount(0);
        run.setStartedAt(OffsetDateTime.now());
        agentRunMapper.insert(run);
        return new AgentRunContext(runId, userId, maxToolCalls);
    }

    /**
     * 在工具执行边界记录 Action 与 Observation，并将异常转换为可审计的失败状态后继续抛出。
     */
    public String executeTool(AgentRunContext context, String toolName, String toolInput,
                              Supplier<String> action) {
        if (!context.toolBudgetAvailable()) {
            recordPolicyRejection(context, toolName, "TOOL_BUDGET_EXCEEDED", toolInput);
            throw new IllegalStateException("本轮工具调用预算已用尽");
        }
        int callStepNo = context.nextStep();
        insertStep(context.runId(), callStepNo, "TOOL_CALL", toolName,
                "调用工具 " + toolName, Map.of("arguments", parseJson(toolInput)));

        ToolExecution execution = new ToolExecution();
        execution.setRunId(context.runId());
        execution.setCallStepNo(callStepNo);
        execution.setToolName(toolName);
        execution.setArgumentJson(parseJson(toolInput));
        execution.setStatus("running");
        execution.setStartedAt(OffsetDateTime.now());
        toolExecutionMapper.insert(execution);

        // 1. 工具开始执行时同步运行级计数，运行中断后仍可判断预算消耗
        updateToolCallCount(context, context.incrementToolCallCount());
        long startedNanos = System.nanoTime();
        try {
            String observation = action.get();
            long durationMs = elapsedMillis(startedNanos);
            int observationStepNo = context.nextStep();
            Object observationJson = parseJson(observation);
            insertStep(context.runId(), observationStepNo, "TOOL_OBSERVATION", toolName,
                    "工具 " + toolName + " 执行成功，耗时 " + durationMs + "ms",
                    Map.of("observation", observationJson, "durationMs", durationMs));

            execution.setObservationStepNo(observationStepNo);
            execution.setObservationJson(observationJson);
            execution.setStatus("success");
            execution.setDurationMs(durationMs);
            execution.setCompletedAt(OffsetDateTime.now());
            toolExecutionMapper.updateById(execution);
            return observation;
        } catch (RuntimeException | Error e) {
            long durationMs = elapsedMillis(startedNanos);
            int errorStepNo = context.nextStep();
            insertStep(context.runId(), errorStepNo, "ERROR", toolName,
                    "工具 " + toolName + " 执行失败", Map.of(
                            "errorType", e.getClass().getSimpleName(),
                            "message", safe(e),
                            "durationMs", durationMs));

            execution.setObservationStepNo(errorStepNo);
            execution.setStatus("failed");
            execution.setDurationMs(durationMs);
            execution.setErrorCode(e.getClass().getSimpleName());
            execution.setErrorMessage(truncate(safe(e)));
            execution.setCompletedAt(OffsetDateTime.now());
            toolExecutionMapper.updateById(execution);
            throw e;
        }
    }

    /**
     * 记录被 Skill 预算策略拒绝的工具调用，便于区分模型问题与工具故障。
     */
    public void recordPolicyRejection(AgentRunContext context, String toolName,
                                      String errorCode, String toolInput) {
        int stepNo = context.nextStep();
        insertStep(context.runId(), stepNo, "POLICY_REJECTION", toolName,
                "工具调用被策略拒绝: " + errorCode, Map.of(
                        "errorCode", errorCode,
                        "arguments", parseJson(toolInput)));

        ToolExecution execution = new ToolExecution();
        execution.setRunId(context.runId());
        execution.setCallStepNo(stepNo);
        execution.setToolName(toolName);
        execution.setArgumentJson(parseJson(toolInput));
        execution.setStatus("rejected");
        execution.setDurationMs(0L);
        execution.setErrorCode(errorCode);
        execution.setErrorMessage("工具调用被 Skill 预算策略拒绝");
        execution.setStartedAt(OffsetDateTime.now());
        execution.setCompletedAt(execution.getStartedAt());
        toolExecutionMapper.insert(execution);
    }

    /**
     * 记录 Route-Intent-Skill 映射结果，使回放能够解释工具和模型权限来源。
     */
    public void recordRouteDecision(AgentRunContext context,
                                    RouteDecision decision,
                                    java.util.Set<String> allowedCommands,
                                    boolean webSearchRequired) {
        insertStep(context.runId(), context.nextStep(), "ROUTE_DECISION", decision.route().name(),
                "请求已映射到显式执行路径 " + decision.route().name(), Map.ofEntries(
                        Map.entry("intent", decision.compatibleIntent().name()),
                        Map.entry("route", decision.route().name()),
                        Map.entry("routeSource", decision.routeSource().name()),
                        Map.entry("subjectType", decision.subjectType().name()),
                        Map.entry("symbols", decision.symbols()),
                        Map.entry("sectors", decision.sectors()),
                        Map.entry("sectorType", decision.sectorType().name()),
                        Map.entry("modelPolicy", decision.modelPolicy().name()),
                        Map.entry("allowedSkillCommands", allowedCommands),
                        Map.entry("webSearchRequired", webSearchRequired),
                        Map.entry("reasonCode", decision.reasonCode()),
                        Map.entry("confidence", decision.confidence())));
    }

    /**
     * 记录每轮 ReAct Decision 的业务摘要与参数指纹，不保存模型隐藏思维链。
     */
    public void recordReactDecision(AgentRunContext context,
                                    int round,
                                    String actionName,
                                    String reasoningSummary,
                                    Map<String, Object> arguments,
                                    String fingerprint) {
        insertStep(context.runId(), context.nextStep(), "REACT_DECISION", actionName,
                "ReAct 第 " + round + " 轮选择 Action " + actionName, Map.of(
                        "round", round,
                        "action", actionName,
                        "reasoningSummary", reasoningSummary == null ? "" : reasoningSummary,
                        "arguments", arguments == null ? Map.of() : arguments,
                        "fingerprint", fingerprint == null ? "" : fingerprint));
    }

    /**
     * 保存统一 ReAct 终止原因，使正常回答、追问和预算阻断使用同一审计口径。
     */
    public void recordReactTermination(AgentRunContext context,
                                       String reason,
                                       int rounds,
                                       int toolCalls,
                                       String detail) {
        insertStep(context.runId(), context.nextStep(), "REACT_TERMINATION", reason,
                "ReAct 已终止: " + reason, Map.of(
                        "reason", reason,
                        "rounds", rounds,
                        "toolCalls", toolCalls,
                        "detail", detail == null ? "" : detail));
    }

    /**
     * 记录付费模型门禁结果，不保存模型隐藏推理过程。
     */
    public void recordModelGate(AgentRunContext context, boolean allowed, String reasonCode) {
        insertStep(context.runId(), context.nextStep(), "MODEL_GATE", "paid-model-gate",
                allowed ? "付费模型门禁已放行" : "付费模型门禁未放行",
                Map.of("allowed", allowed, "reasonCode", reasonCode));
    }

    /**
     * 记录最终使用的模型等级，便于核对非付费 Route 的调用次数。
     */
    public void recordModelCall(AgentRunContext context, String modelTier, String purpose) {
        insertStep(context.runId(), context.nextStep(), "MODEL_CALL", modelTier,
                "执行最终回答模型", Map.of("modelTier", modelTier, "purpose", purpose));
    }

    /**
     * 完成运行并保存最终回答，形成可回放链路的终点。
     */
    public void complete(AgentRunContext context, String answer) {
        insertStep(context.runId(), context.nextStep(), "FINAL_ANSWER", "assistant",
                "Agent 生成最终回答", Map.of("answer", truncate(answer)));

        AgentRun run = requireRun(context.runId());
        run.setStatus("completed");
        run.setFinalAnswer(answer);
        run.setToolCallCount(context.toolCallCount());
        run.setCompletedAt(OffsetDateTime.now());
        agentRunMapper.updateById(run);
    }

    /**
     * 将未正常结束的运行标为失败，并保存对外可诊断的错误摘要。
     */
    public void fail(AgentRunContext context, Throwable error) {
        insertStep(context.runId(), context.nextStep(), "ERROR", "agent",
                "Agent Run 执行失败", Map.of(
                        "errorType", error.getClass().getSimpleName(),
                        "message", safe(error)));

        AgentRun run = requireRun(context.runId());
        run.setStatus("failed");
        run.setToolCallCount(context.toolCallCount());
        run.setErrorMessage(truncate(safe(error)));
        run.setCompletedAt(OffsetDateTime.now());
        agentRunMapper.updateById(run);
    }

    /**
     * 按 Run ID 返回归属用户可访问的完整审计记录。
     */
    public AgentRunReplay replay(UUID runId, Long userId) {
        AgentRun run = requireRun(runId);
        if (!run.getUserId().equals(userId)) {
            throw new SecurityException("无权访问该 Agent Run");
        }
        List<AgentStep> steps = agentStepMapper.selectList(
                new LambdaQueryWrapper<AgentStep>()
                        .eq(AgentStep::getRunId, runId)
                        .orderByAsc(AgentStep::getStepNo));
        List<ToolExecution> executions = toolExecutionMapper.selectList(
                new LambdaQueryWrapper<ToolExecution>()
                        .eq(ToolExecution::getRunId, runId)
                        .orderByAsc(ToolExecution::getCallStepNo));
        return new AgentRunReplay(run, steps, executions);
    }

    /**
     * 查询用户最近的 Agent Run，用于定位待回放记录。
     */
    public List<AgentRun> listRecent(Long userId, int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return agentRunMapper.selectList(new LambdaQueryWrapper<AgentRun>()
                .eq(AgentRun::getUserId, userId)
                .orderByDesc(AgentRun::getStartedAt)
                .last("LIMIT " + safeLimit));
    }

    private void insertStep(UUID runId, int stepNo, String type, String name,
                            String summary, Map<String, Object> payload) {
        AgentStep step = new AgentStep();
        step.setRunId(runId);
        step.setStepNo(stepNo);
        step.setStepType(type);
        step.setName(name);
        step.setSummary(summary);
        step.setPayload(payload);
        step.setCreatedAt(OffsetDateTime.now());
        agentStepMapper.insert(step);
    }

    private void updateToolCallCount(AgentRunContext context, int count) {
        AgentRun run = new AgentRun();
        run.setRunId(context.runId());
        run.setToolCallCount(count);
        agentRunMapper.updateById(run);
    }

    private AgentRun requireRun(UUID runId) {
        AgentRun run = agentRunMapper.selectById(runId);
        if (run == null) {
            throw new NoSuchElementException("Agent Run 不存在: " + runId);
        }
        return run;
    }

    private Object parseJson(String text) {
        String safeText = truncate(text);
        if (safeText.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(safeText, Object.class);
        } catch (Exception e) {
            return Map.of("raw", safeText);
        }
    }

    private int intConstraint(SkillDefinition skill, String name, int defaultValue) {
        Object value = skill.constraints().get(name);
        if (value instanceof Number number) {
            return Math.max(0, number.intValue());
        }
        return defaultValue;
    }

    private long elapsedMillis(long startedNanos) {
        return Math.max(0L, (System.nanoTime() - startedNanos) / 1_000_000L);
    }

    private String truncate(String text) {
        if (text == null) {
            return "";
        }
        if (text.length() <= MAX_AUDIT_TEXT_LENGTH) {
            return text;
        }
        return text.substring(0, MAX_AUDIT_TEXT_LENGTH) + "…";
    }

    private String safe(Throwable error) {
        String message = error.getMessage();
        return message == null ? error.getClass().getSimpleName() : truncate(message);
    }
}
