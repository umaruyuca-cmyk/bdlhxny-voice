package com.bdlh.runtime.agent.react;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.bdlh.runtime.agent.AgentRunContext;
import com.bdlh.runtime.agent.routing.RouteDecision;
import com.bdlh.runtime.agent.routing.RouteExecutionPolicyRegistry;
import com.bdlh.runtime.service.AgentRunService;
import com.bdlh.runtime.skill.SkillDefinition;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * 在初始 Route 权限上执行有界 Decision/Action/Observation 循环，统一限制轮次、时间和重复调用。
 */
@Component
public class BoundedReactLoop {

    private static final int DEFAULT_MAX_TOOL_CALLS = 6;

    private final RouteExecutionPolicyRegistry policyRegistry;
    private final AgentRunService agentRunService;
    private final ObjectMapper canonicalMapper;
    private final int defaultMaxSteps;
    private final long defaultDeadlineMs;
    private final long defaultToolTimeoutMs;
    private final int defaultMaxSameAction;
    private final int defaultObservationChars;
    private final ExecutorService toolExecutor;

    @Autowired
    public BoundedReactLoop(RouteExecutionPolicyRegistry policyRegistry,
                            AgentRunService agentRunService,
                            ObjectMapper objectMapper,
                            @Value("${bdlh_runtime.react.max-steps:5}") int defaultMaxSteps,
                            @Value("${bdlh_runtime.react.deadline-ms:180000}") long defaultDeadlineMs,
                            @Value("${bdlh_runtime.react.tool-timeout-ms:60000}") long defaultToolTimeoutMs,
                            @Value("${bdlh_runtime.react.max-same-action:1}") int defaultMaxSameAction,
                            @Value("${bdlh_runtime.react.max-observation-chars:8000}") int defaultObservationChars,
                            @Qualifier("reactToolExecutor") ExecutorService toolExecutor) {
        this.policyRegistry = policyRegistry;
        this.agentRunService = agentRunService;
        this.canonicalMapper = objectMapper.copy()
                .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);
        this.defaultMaxSteps = positive(defaultMaxSteps, 5);
        this.defaultDeadlineMs = positive(defaultDeadlineMs, 180_000L);
        this.defaultToolTimeoutMs = positive(defaultToolTimeoutMs, 60_000L);
        this.defaultMaxSameAction = positive(defaultMaxSameAction, 1);
        this.defaultObservationChars = positive(defaultObservationChars, 8_000);
        this.toolExecutor = toolExecutor;
    }

    /**
     * 为不启动Spring容器的单元测试创建小型有界工具线程池。
     */
    public BoundedReactLoop(RouteExecutionPolicyRegistry policyRegistry,
                            AgentRunService agentRunService,
                            ObjectMapper objectMapper,
                            int defaultMaxSteps,
                            long defaultDeadlineMs,
                            long defaultToolTimeoutMs,
                            int defaultMaxSameAction,
                            int defaultObservationChars) {
        this(
                policyRegistry,
                agentRunService,
                objectMapper,
                defaultMaxSteps,
                defaultDeadlineMs,
                defaultToolTimeoutMs,
                defaultMaxSameAction,
                defaultObservationChars,
                Executors.newFixedThreadPool(2));
    }

    /**
     * 逐轮执行 Route 预先规划的 Action，任一硬限制触发后立即停止且不执行后续动作。
     */
    public ReactLoopResult execute(RouteDecision decision,
                                   SkillDefinition skill,
                                   AgentRunContext runContext,
                                   List<ReactToolAction> actions) {
        List<ReactToolAction> safeActions = actions == null ? List.of() : List.copyOf(actions);
        List<ReactObservation> observations = new ArrayList<>();
        Map<String, Integer> fingerprints = new LinkedHashMap<>();
        int maxSteps = boundedIntConstraint(skill, "maxReactSteps", defaultMaxSteps);
        int maxToolCalls = boundedIntConstraint(skill, "maxToolCalls", DEFAULT_MAX_TOOL_CALLS);
        int maxSameAction = boundedIntConstraint(skill, "maxSameToolCall", defaultMaxSameAction);
        int observationChars = boundedIntConstraint(
                skill, "maxObservationChars", defaultObservationChars);
        long deadlineMs = boundedLongConstraint(skill, "reactDeadlineMs", defaultDeadlineMs);
        long toolTimeoutMs = boundedLongConstraint(skill, "toolTimeoutMs", defaultToolTimeoutMs);
        long startedNanos = System.nanoTime();
        int rounds = 0;
        int toolCalls = 0;

        for (ReactToolAction action : safeActions) {
            if (rounds >= maxSteps) {
                return result(observations, ReactTerminationReason.MAX_STEPS_REACHED,
                        rounds, toolCalls, "已达到最大 ReAct 轮数 " + maxSteps);
            }
            long remainingMs = remainingMillis(startedNanos, deadlineMs);
            if (remainingMs <= 0) {
                return result(observations, ReactTerminationReason.DEADLINE_EXCEEDED,
                        rounds, toolCalls, "已达到 ReAct 总截止时间");
            }

            // 1. 每个 Action 都先形成可审计 Decision，再执行权限和预算校验
            rounds++;
            String fingerprint = fingerprint(action);
            agentRunService.recordReactDecision(
                    runContext, rounds, action.toolName(), action.reasoningSummary(),
                    action.arguments(), fingerprint);

            if (!policyRegistry.allowsAction(decision.route(), action.toolName())) {
                agentRunService.recordPolicyRejection(
                        runContext, action.toolName(), "REACT_ACTION_NOT_ALLOWED", json(action.arguments()));
                return result(observations, ReactTerminationReason.POLICY_REJECTED,
                        rounds, toolCalls, "初始 Route 不允许工具 " + action.toolName());
            }
            if (toolCalls >= maxToolCalls) {
                agentRunService.recordPolicyRejection(
                        runContext, action.toolName(), "REACT_TOOL_BUDGET_EXCEEDED", json(action.arguments()));
                return result(observations, ReactTerminationReason.TOOL_BUDGET_EXCEEDED,
                        rounds, toolCalls, "已达到 ReAct 工具调用预算 " + maxToolCalls);
            }
            int sameCalls = fingerprints.getOrDefault(fingerprint, 0);
            if (sameCalls >= maxSameAction) {
                agentRunService.recordPolicyRejection(
                        runContext, action.toolName(), "DUPLICATE_REACT_ACTION_BLOCKED", json(action.arguments()));
                return result(observations, ReactTerminationReason.DUPLICATE_ACTION_BLOCKED,
                        rounds, toolCalls, "相同 Action 与参数已达到调用上限");
            }

            // 2. 只有通过权限、总量和重复检查的 Action 才消耗调用预算
            fingerprints.put(fingerprint, sameCalls + 1);
            toolCalls++;
            long actionStartedNanos = System.nanoTime();
            Future<String> future;
            try {
                future = toolExecutor.submit(() -> agentRunService.executeTool(
                        runContext, action.toolName(), json(action.arguments()), action.execution()));
            } catch (RejectedExecutionException error) {
                return result(observations, ReactTerminationReason.SYSTEM_BUSY,
                        rounds, toolCalls, "ReAct工具执行队列已满");
            }
            try {
                long timeoutMs = Math.max(1L, Math.min(toolTimeoutMs, remainingMs));
                String output = future.get(timeoutMs, TimeUnit.MILLISECONDS);
                observations.add(new ReactObservation(
                        action.toolName(),
                        output,
                        truncate(output, observationChars),
                        elapsedMillis(actionStartedNanos)));
            } catch (TimeoutException e) {
                future.cancel(true);
                return result(observations,
                        remainingMillis(startedNanos, deadlineMs) <= 0
                                ? ReactTerminationReason.DEADLINE_EXCEEDED
                                : ReactTerminationReason.TOOL_TIMEOUT,
                        rounds, toolCalls, "工具 " + action.toolName() + " 执行超时");
            } catch (InterruptedException e) {
                future.cancel(true);
                Thread.currentThread().interrupt();
                return result(observations, ReactTerminationReason.TOOL_FAILED,
                        rounds, toolCalls, "ReAct 执行线程被中断");
            } catch (ExecutionException e) {
                return result(observations, ReactTerminationReason.TOOL_FAILED,
                        rounds, toolCalls, safe(e.getCause()));
            }
        }
        return result(observations, ReactTerminationReason.ACTION_PLAN_COMPLETED,
                rounds, toolCalls, "Route Action 计划执行完成");
    }

    /**
     * 关闭内部工具执行线程，避免应用停止后残留工作线程。
     */
    @PreDestroy
    public void close() {
        toolExecutor.shutdownNow();
    }

    private ReactLoopResult result(List<ReactObservation> observations,
                                   ReactTerminationReason reason,
                                   int rounds,
                                   int toolCalls,
                                   String detail) {
        return new ReactLoopResult(observations, reason, rounds, toolCalls, detail);
    }

    private String fingerprint(ReactToolAction action) {
        try {
            String canonical = action.toolName() + "\n"
                    + canonicalMapper.writeValueAsString(action.arguments());
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(canonical.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (Exception e) {
            throw new IllegalStateException("生成 ReAct Action 指纹失败", e);
        }
    }

    private String json(Object value) {
        try {
            return canonicalMapper.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("序列化 ReAct Action 参数失败", e);
        }
    }

    private int boundedIntConstraint(SkillDefinition skill, String name, int globalMaximum) {
        Object value = skill.constraints().get(name);
        if (value instanceof Number number) {
            return Math.min(globalMaximum, Math.max(0, number.intValue()));
        }
        return globalMaximum;
    }

    private long boundedLongConstraint(SkillDefinition skill, String name, long globalMaximum) {
        Object value = skill.constraints().get(name);
        if (value instanceof Number number) {
            return Math.min(globalMaximum, Math.max(0L, number.longValue()));
        }
        return globalMaximum;
    }

    private long remainingMillis(long startedNanos, long deadlineMs) {
        return deadlineMs - elapsedMillis(startedNanos);
    }

    private long elapsedMillis(long startedNanos) {
        return Math.max(0L, Duration.ofNanos(System.nanoTime() - startedNanos).toMillis());
    }

    private String truncate(String value, int maxLength) {
        String safeValue = value == null ? "" : value;
        if (safeValue.length() <= maxLength) {
            return safeValue;
        }
        return safeValue.substring(0, maxLength) + "…";
    }

    private String safe(Throwable error) {
        if (error == null) {
            return "工具执行失败";
        }
        return error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
    }

    private int positive(int value, int fallback) {
        return value > 0 ? value : fallback;
    }

    private long positive(long value, long fallback) {
        return value > 0 ? value : fallback;
    }
}
