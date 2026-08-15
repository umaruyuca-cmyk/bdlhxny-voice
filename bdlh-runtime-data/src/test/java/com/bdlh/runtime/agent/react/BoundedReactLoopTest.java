package com.bdlh.runtime.agent.react;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.bdlh.runtime.agent.AgentRunContext;
import com.bdlh.runtime.agent.routing.ModelPolicy;
import com.bdlh.runtime.agent.routing.RequestRoute;
import com.bdlh.runtime.agent.routing.RouteDecision;
import com.bdlh.runtime.agent.routing.RouteExecutionPolicyRegistry;
import com.bdlh.runtime.llm.ChatIntent;
import com.bdlh.runtime.service.AgentRunService;
import com.bdlh.runtime.skill.SkillDefinition;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证有界 ReAct 的轮次、重复 Action、权限和超时终止边界。
 */
class BoundedReactLoopTest {

    private AgentRunService agentRunService;
    private BoundedReactLoop loop;

    @BeforeEach
    void setUp() {
        agentRunService = mock(AgentRunService.class);
        when(agentRunService.executeTool(any(), anyString(), anyString(), any()))
                .thenAnswer(invocation -> {
                    Supplier<String> action = invocation.getArgument(3);
                    return action.get();
                });
        loop = new BoundedReactLoop(
                new RouteExecutionPolicyRegistry(),
                agentRunService,
                new ObjectMapper(),
                5,
                180_000,
                60_000,
                1,
                8_000);
    }

    @AfterEach
    void tearDown() {
        loop.close();
    }

    @Test
    void shouldExecuteCausalActionsInStableOrder() {
        List<String> calls = new ArrayList<>();
        ReactLoopResult result = loop.execute(
                decision(RequestRoute.MARKET_CAUSAL_ANALYSIS),
                skill(Map.of("maxReactSteps", 5, "maxToolCalls", 3)),
                context(),
                List.of(
                        action("stock", Map.of("symbol", "600519"), () -> {
                            calls.add("stock");
                            return "{\"stock\":true}";
                        }),
                        action("webSearch", Map.of("taskCount", 1), () -> {
                            calls.add("webSearch");
                            return "{\"results\":[]}";
                        })));

        assertThat(result.completed()).isTrue();
        assertThat(result.terminationReason()).isEqualTo(ReactTerminationReason.ACTION_PLAN_COMPLETED);
        assertThat(result.rounds()).isEqualTo(2);
        assertThat(result.toolCalls()).isEqualTo(2);
        assertThat(calls).containsExactly("stock", "webSearch");
    }

    @Test
    void shouldStopBeforeActionBeyondMaxSteps() {
        ReactLoopResult result = loop.execute(
                decision(RequestRoute.MARKET_CAUSAL_ANALYSIS),
                skill(Map.of("maxReactSteps", 1, "maxToolCalls", 3)),
                context(),
                List.of(
                        action("stock", Map.of("symbol", "600519"), () -> "{}"),
                        action("webSearch", Map.of("taskCount", 1), () -> "{}")));

        assertThat(result.terminationReason()).isEqualTo(ReactTerminationReason.MAX_STEPS_REACHED);
        assertThat(result.rounds()).isEqualTo(1);
        assertThat(result.toolCalls()).isEqualTo(1);
    }

    @Test
    void shouldBlockDuplicateToolAndArguments() {
        ReactToolAction repeated = action("stock", Map.of("symbol", "600519"), () -> "{}");

        ReactLoopResult result = loop.execute(
                decision(RequestRoute.STOCK_DECISION),
                skill(Map.of(
                        "maxReactSteps", 3,
                        "maxToolCalls", 3,
                        "maxSameToolCall", 1)),
                context(),
                List.of(repeated, repeated));

        assertThat(result.terminationReason())
                .isEqualTo(ReactTerminationReason.DUPLICATE_ACTION_BLOCKED);
        assertThat(result.rounds()).isEqualTo(2);
        assertThat(result.toolCalls()).isEqualTo(1);
        verify(agentRunService).recordPolicyRejection(
                any(), anyString(), anyString(), anyString());
    }

    @Test
    void shouldStopBeforeActionBeyondToolBudget() {
        ReactLoopResult result = loop.execute(
                decision(RequestRoute.MARKET_CAUSAL_ANALYSIS),
                skill(Map.of("maxReactSteps", 3, "maxToolCalls", 1)),
                context(),
                List.of(
                        action("stock", Map.of("symbol", "600519"), () -> "{}"),
                        action("webSearch", Map.of("taskCount", 1), () -> "{}")));

        assertThat(result.terminationReason())
                .isEqualTo(ReactTerminationReason.TOOL_BUDGET_EXCEEDED);
        assertThat(result.toolCalls()).isEqualTo(1);
    }

    @Test
    void shouldRejectActionOutsideInitialRoute() {
        ReactLoopResult result = loop.execute(
                decision(RequestRoute.GENERAL_CHAT),
                skill(Map.of("maxReactSteps", 2, "maxToolCalls", 2)),
                context(),
                List.of(action("stock", Map.of("symbol", "600519"), () -> "{}")));

        assertThat(result.terminationReason()).isEqualTo(ReactTerminationReason.POLICY_REJECTED);
        verify(agentRunService, never()).executeTool(any(), anyString(), anyString(), any());
    }

    @Test
    void shouldStopAtOverallDeadline() {
        loop.close();
        loop = new BoundedReactLoop(
                new RouteExecutionPolicyRegistry(),
                agentRunService,
                new ObjectMapper(),
                5,
                20,
                1_000,
                1,
                8_000);

        ReactLoopResult result = loop.execute(
                decision(RequestRoute.STOCK_DECISION),
                skill(Map.of(
                        "maxReactSteps", 2,
                        "maxToolCalls", 2,
                        "reactDeadlineMs", 20,
                        "toolTimeoutMs", 1_000)),
                context(),
                List.of(action("stock", Map.of("symbol", "600519"), () -> {
                    try {
                        Thread.sleep(200);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                    return "{}";
                })));

        assertThat(result.terminationReason()).isEqualTo(ReactTerminationReason.DEADLINE_EXCEEDED);
    }

    @Test
    void shouldStopAtSingleToolTimeout() {
        loop.close();
        loop = new BoundedReactLoop(
                new RouteExecutionPolicyRegistry(),
                agentRunService,
                new ObjectMapper(),
                5,
                1_000,
                20,
                1,
                8_000);

        ReactLoopResult result = loop.execute(
                decision(RequestRoute.STOCK_DECISION),
                skill(Map.of(
                        "maxReactSteps", 2,
                        "maxToolCalls", 2,
                        "reactDeadlineMs", 1_000,
                        "toolTimeoutMs", 20)),
                context(),
                List.of(action("stock", Map.of("symbol", "600519"), () -> {
                    try {
                        Thread.sleep(200);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                    return "{}";
                })));

        assertThat(result.terminationReason()).isEqualTo(ReactTerminationReason.TOOL_TIMEOUT);
    }

    private ReactToolAction action(String name, Map<String, Object> arguments, Supplier<String> execution) {
        return new ReactToolAction(name, arguments, "测试决策摘要", execution);
    }

    private AgentRunContext context() {
        return new AgentRunContext(UUID.randomUUID(), 10);
    }

    private SkillDefinition skill(Map<String, Object> constraints) {
        return new SkillDefinition(
                "test-skill",
                "1.0.0",
                "测试 Skill",
                "测试",
                List.of(),
                constraints,
                List.of());
    }

    private RouteDecision decision(RequestRoute route) {
        return new RouteDecision(
                route,
                route == RequestRoute.GENERAL_CHAT ? ChatIntent.GENERAL_CHAT : ChatIntent.STOCK_ANALYSIS,
                route == RequestRoute.GENERAL_CHAT
                        ? ModelPolicy.LOCAL_ONLY
                        : ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
                "600519",
                "TEST",
                1.0,
                true,
                route == RequestRoute.MARKET_CAUSAL_ANALYSIS,
                false,
                null);
    }
}
