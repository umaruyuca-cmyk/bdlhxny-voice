package com.bdlh.runtime.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.bdlh.runtime.agent.AgentRunContext;
import com.bdlh.runtime.entity.AgentRun;
import com.bdlh.runtime.entity.AgentStep;
import com.bdlh.runtime.entity.ToolExecution;
import com.bdlh.runtime.llm.ChatIntent;
import com.bdlh.runtime.mapper.AgentRunMapper;
import com.bdlh.runtime.mapper.AgentStepMapper;
import com.bdlh.runtime.mapper.ToolExecutionMapper;
import com.bdlh.runtime.skill.SkillDefinition;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证 Agent Run 的生命周期、工具审计与策略拒绝记录。
 */
class AgentRunServiceTest {

    private AgentRunMapper agentRunMapper;
    private AgentStepMapper agentStepMapper;
    private ToolExecutionMapper toolExecutionMapper;
    private AgentRunService service;

    @BeforeEach
    void setUp() {
        agentRunMapper = mock(AgentRunMapper.class);
        agentStepMapper = mock(AgentStepMapper.class);
        toolExecutionMapper = mock(ToolExecutionMapper.class);
        service = new AgentRunService(
                agentRunMapper, agentStepMapper, toolExecutionMapper, new ObjectMapper());
    }

    @Test
    void shouldStartRunWithSkillVersionAndBudget() {
        AgentRunContext context = service.start(
                7L, "session-1", "分析 588200", ChatIntent.STOCK_ANALYSIS, skill());

        ArgumentCaptor<AgentRun> captor = ArgumentCaptor.forClass(AgentRun.class);
        verify(agentRunMapper).insert(captor.capture());
        AgentRun run = captor.getValue();
        assertEquals(context.runId(), run.getRunId());
        assertEquals("test-skill", run.getSkillName());
        assertEquals("2.0.0", run.getSkillVersion());
        assertEquals(3, run.getMaxToolCalls());
        assertEquals("running", run.getStatus());
    }

    @Test
    void shouldPersistToolActionAndObservation() {
        AgentRunContext context = new AgentRunContext(UUID.randomUUID());

        String result = service.executeTool(
                context, "analyzeStock", "{\"code\":\"588200\"}",
                () -> "{\"success\":true}");

        assertEquals("{\"success\":true}", result);
        assertEquals(1, context.toolCallCount());
        ArgumentCaptor<AgentStep> stepCaptor = ArgumentCaptor.forClass(AgentStep.class);
        verify(agentStepMapper, times(2)).insert(stepCaptor.capture());
        assertEquals(List.of("TOOL_CALL", "TOOL_OBSERVATION"),
                stepCaptor.getAllValues().stream().map(AgentStep::getStepType).toList());
        ArgumentCaptor<ToolExecution> executionCaptor = ArgumentCaptor.forClass(ToolExecution.class);
        verify(toolExecutionMapper).updateById(executionCaptor.capture());
        assertEquals("success", executionCaptor.getValue().getStatus());
    }

    @Test
    void shouldPersistFailedToolExecutionAndRethrow() {
        AgentRunContext context = new AgentRunContext(UUID.randomUUID());

        IllegalStateException thrown = assertThrows(IllegalStateException.class,
                () -> service.executeTool(context, "analyzeStock", "{}",
                        () -> {
                            throw new IllegalStateException("CLI 不可用");
                        }));

        assertEquals("CLI 不可用", thrown.getMessage());
        ArgumentCaptor<ToolExecution> captor = ArgumentCaptor.forClass(ToolExecution.class);
        verify(toolExecutionMapper).updateById(captor.capture());
        assertEquals("failed", captor.getValue().getStatus());
        assertEquals("IllegalStateException", captor.getValue().getErrorCode());
    }

    @Test
    void shouldRecordPolicyRejectionWithoutConsumingToolCount() {
        AgentRunContext context = new AgentRunContext(UUID.randomUUID());

        service.recordPolicyRejection(
                context, "analyzeStock", "DUPLICATE_TOOL_CALL_BLOCKED", "{}");

        assertEquals(0, context.toolCallCount());
        ArgumentCaptor<AgentStep> stepCaptor = ArgumentCaptor.forClass(AgentStep.class);
        verify(agentStepMapper).insert(stepCaptor.capture());
        assertEquals("POLICY_REJECTION", stepCaptor.getValue().getStepType());
        ArgumentCaptor<ToolExecution> executionCaptor = ArgumentCaptor.forClass(ToolExecution.class);
        verify(toolExecutionMapper).insert(executionCaptor.capture());
        assertEquals("rejected", executionCaptor.getValue().getStatus());
    }

    @Test
    void shouldPersistReactDecisionAndTermination() {
        AgentRunContext context = new AgentRunContext(UUID.randomUUID());

        service.recordReactDecision(
                context,
                1,
                "stock",
                "先核验行情",
                Map.of("symbol", "600519"),
                "fingerprint");
        service.recordReactTermination(
                context,
                "FINAL_ANSWER",
                1,
                1,
                "证据已满足");

        ArgumentCaptor<AgentStep> captor = ArgumentCaptor.forClass(AgentStep.class);
        verify(agentStepMapper, times(2)).insert(captor.capture());
        assertEquals(List.of("REACT_DECISION", "REACT_TERMINATION"),
                captor.getAllValues().stream().map(AgentStep::getStepType).toList());
        assertEquals("FINAL_ANSWER", captor.getAllValues().get(1).getPayload().get("reason"));
    }

    @Test
    void shouldCompleteRunWithFinalAnswer() {
        UUID runId = UUID.randomUUID();
        AgentRunContext context = new AgentRunContext(runId);
        AgentRun stored = new AgentRun();
        stored.setRunId(runId);
        stored.setUserId(7L);
        when(agentRunMapper.selectById(runId)).thenReturn(stored);

        service.complete(context, "结论");

        assertEquals("completed", stored.getStatus());
        assertEquals("结论", stored.getFinalAnswer());
        assertTrue(stored.getCompletedAt() != null);
        verify(agentRunMapper).updateById(stored);
    }

    private SkillDefinition skill() {
        return new SkillDefinition(
                "test-skill",
                "2.0.0",
                "测试",
                "测试",
                List.of("analyzeStock"),
                Map.of("maxToolCalls", 3),
                List.of());
    }
}
