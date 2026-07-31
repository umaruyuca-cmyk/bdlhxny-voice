package com.stockwise.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.agent.AgentRunContext;
import com.stockwise.service.AgentRunService;
import com.stockwise.service.KnowledgeFilter;
import com.stockwise.service.KnowledgeRetrievalService;
import com.stockwise.skill.SkillDefinition;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.ToolCallback;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证 Skill 工具白名单与单次请求的重复调用预算。
 */
class SkillToolResolverTest {

    @Test
    void shouldExposeOnlyWhitelistedTools() {
        SkillToolResolver resolver = resolver(mock(StockAnalysisGateway.class));
        SkillDefinition skill = skill(
                List.of("analyzePortfolio", "analyzeQuant"),
                Map.of("maxToolCalls", 3, "maxSameToolCall", 1));

        List<String> names = resolver.resolve(skill).stream()
                .map(callback -> callback.getToolDefinition().name())
                .toList();

        assertEquals(List.of("analyzePortfolio", "analyzeQuant"), names);
    }

    @Test
    void shouldExposeNoToolsForGeneralChat() {
        SkillToolResolver resolver = resolver(mock(StockAnalysisGateway.class));

        assertTrue(resolver.resolve(skill(List.of(), Map.of("maxToolCalls", 0))).isEmpty());
    }

    @Test
    void shouldBlockDuplicateToolCallWithinOneRun() {
        StockAnalysisGateway gateway = mock(StockAnalysisGateway.class);
        when(gateway.stock("588200", "etf")).thenReturn("""
                {
                  "schemaVersion":"1.1",
                  "command":"stock",
                  "timezone":"Asia/Shanghai",
                  "asOf":"2026-07-27 10:00:00",
                  "dataQuality":{"status":"verified","allowsDirectionalSignal":true},
                  "methodology":{
                    "id":"stockwise-objective-analysis",
                    "version":"1.0.0",
                    "rules":[{"ruleId":"DATA-FRESH-001"}]
                  },
                  "decisionBasis":{"verdict":"hold"},
                  "data":{
                    "dataQuality":{"allowsDirectionalSignal":true},
                    "chase":{"level":"none"}
                  }
                }
                """);
        SkillToolResolver resolver = resolver(gateway);
        ToolCallback callback = resolver.resolve(skill(
                List.of("analyzeStock"),
                Map.of("maxToolCalls", 2, "maxSameToolCall", 1))).get(0);
        String arguments = "{\"code\":\"588200\",\"assetType\":\"etf\"}";

        String first = callback.call(arguments);
        String second = callback.call(arguments);

        assertTrue(first.contains("consumerPolicy"));
        assertTrue(second.contains("DUPLICATE_TOOL_CALL_BLOCKED"));
    }

    @Test
    void shouldAuditAllowedAndRejectedToolCalls() {
        StockAnalysisGateway gateway = mock(StockAnalysisGateway.class);
        when(gateway.stock("588200", "etf")).thenReturn("""
                {
                  "schemaVersion":"1.1",
                  "command":"stock",
                  "timezone":"Asia/Shanghai",
                  "asOf":"2026-07-27 10:00:00",
                  "dataQuality":{"status":"verified","allowsDirectionalSignal":true},
                  "methodology":{
                    "id":"stockwise-objective-analysis",
                    "version":"1.0.0",
                    "rules":[{"ruleId":"DATA-FRESH-001"}]
                  },
                  "decisionBasis":{"verdict":"hold"},
                  "data":{
                    "dataQuality":{"allowsDirectionalSignal":true},
                    "chase":{"level":"none"}
                  }
                }
                """);
        AgentRunService runService = mock(AgentRunService.class);
        when(runService.executeTool(
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any()))
                .thenAnswer(invocation -> {
                    Supplier<String> action = invocation.getArgument(3);
                    return action.get();
                });
        AgentRunContext context = new AgentRunContext(UUID.randomUUID());
        ToolCallback callback = resolver(gateway, runService).resolve(
                skill(List.of("analyzeStock"), Map.of("maxToolCalls", 2, "maxSameToolCall", 1)),
                context).get(0);
        String arguments = "{\"code\":\"588200\",\"assetType\":\"etf\"}";

        callback.call(arguments);
        callback.call(arguments);

        verify(runService, times(1)).executeTool(
                org.mockito.ArgumentMatchers.eq(context),
                org.mockito.ArgumentMatchers.eq("analyzeStock"),
                org.mockito.ArgumentMatchers.eq(arguments),
                org.mockito.ArgumentMatchers.any());
        verify(runService).recordPolicyRejection(
                context, "analyzeStock", "DUPLICATE_TOOL_CALL_BLOCKED", arguments);
    }

    private SkillToolResolver resolver(StockAnalysisGateway gateway) {
        return resolver(gateway, mock(AgentRunService.class));
    }

    private SkillToolResolver resolver(StockAnalysisGateway gateway, AgentRunService runService) {
        ObjectMapper mapper = new ObjectMapper();
        StockSkillContractValidator validator = new StockSkillContractValidator(mapper);
        StockTools tools = new StockTools(
                gateway,
                mock(KnowledgeRetrievalService.class),
                mock(KnowledgeFilter.class),
                validator,
                mapper);
        return new SkillToolResolver(tools, runService);
    }

    private SkillDefinition skill(List<String> tools, Map<String, Object> constraints) {
        return new SkillDefinition(
                "test-skill",
                "1.0.0",
                "测试",
                "测试",
                tools,
                constraints,
                List.of());
    }
}
