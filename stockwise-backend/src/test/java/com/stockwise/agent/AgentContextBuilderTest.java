package com.stockwise.agent;

import com.stockwise.agent.context.ConservativeTokenCountEstimator;
import com.stockwise.agent.context.ContextBudgetPolicy;
import com.stockwise.agent.context.LangChainContextWindow;
import com.stockwise.memory.ConversationMessage;
import com.stockwise.memory.SessionState;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证工作记忆与跨会话摘要的上下文组装边界。
 */
class AgentContextBuilderTest {

    private final ConservativeTokenCountEstimator tokenEstimator = new ConservativeTokenCountEstimator();
    private final AgentContextBuilder builder = new AgentContextBuilder(
            new ContextBudgetPolicy(10, 2000, 4000, 800, 3, 900),
            new LangChainContextWindow(tokenEstimator),
            tokenEstimator);

    @Test
    void shouldMergeSummariesAndRecentHistoryWithoutDuplicatingCurrentMessage() {
        SessionState state = new SessionState();
        state.setRecentConversationSummaries(List.of("上次讨论了 ETF 风险。"));
        state.setHistory(List.of(
                ConversationMessage.user("上一问"),
                ConversationMessage.assistant("上一答"),
                ConversationMessage.user("分析 588200")
        ));

        String prompt = builder.build(state, "分析 588200");

        assertTrue(prompt.contains("上次讨论了 ETF 风险"));
        assertTrue(prompt.contains("user: 上一问"));
        assertTrue(prompt.contains("assistant: 上一答"));
        assertTrue(prompt.contains("当前用户问题：\n分析 588200"));
        assertEquals(1, occurrences(prompt, "分析 588200"));
    }

    @Test
    void shouldNotCreateEmptyHistorySection() {
        SessionState state = new SessionState();

        String prompt = builder.build(state, "你好");

        assertFalse(prompt.contains("当前会话最近消息"));
        assertEquals("当前用户问题：\n你好", prompt);
    }

    @Test
    void shouldKeepCurrentQuestionEvenWhenHistoryBudgetIsSmall() {
        AgentContextBuilder smallBuilder = new AgentContextBuilder(
                new ContextBudgetPolicy(10, 12, 12, 6, 1, 4),
                new LangChainContextWindow(tokenEstimator),
                tokenEstimator);
        SessionState state = new SessionState();
        state.setHistory(List.of(
                ConversationMessage.user("很长的历史问题很长的历史问题"),
                ConversationMessage.assistant("很长的历史回答很长的历史回答"),
                ConversationMessage.user("当前问题必须完整保留")
        ));

        String prompt = smallBuilder.build(state, "当前问题必须完整保留");

        assertTrue(prompt.endsWith("当前用户问题：\n当前问题必须完整保留"));
        assertEquals(1, occurrences(prompt, "当前问题必须完整保留"));
    }

    private int occurrences(String text, String target) {
        int count = 0;
        int offset = 0;
        while ((offset = text.indexOf(target, offset)) >= 0) {
            count++;
            offset += target.length();
        }
        return count;
    }
}
