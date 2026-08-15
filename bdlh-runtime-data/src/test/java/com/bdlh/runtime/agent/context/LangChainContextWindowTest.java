package com.bdlh.runtime.agent.context;

import com.bdlh.runtime.memory.ConversationMessage;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证 LangChain4j 上下文窗口同时遵守会话隔离、消息数和 Token 边界。
 */
class LangChainContextWindowTest {

    private final ConservativeTokenCountEstimator estimator = new ConservativeTokenCountEstimator();
    private final LangChainContextWindow window = new LangChainContextWindow(estimator);

    @Test
    void shouldKeepOnlyLatestMessagesWithinMessageLimit() {
        List<ConversationMessage> result = window.trim(
                "1:session-a",
                List.of(
                        ConversationMessage.user("第一问"),
                        ConversationMessage.assistant("第一答"),
                        ConversationMessage.user("第二问"),
                        ConversationMessage.assistant("第二答")
                ),
                2,
                100,
                50);

        assertEquals(List.of(
                ConversationMessage.user("第二问"),
                ConversationMessage.assistant("第二答")
        ), result);
    }

    @Test
    void shouldNotLeakMessagesAcrossSessionWindows() {
        List<ConversationMessage> first = window.trim(
                "1:session-a",
                List.of(ConversationMessage.user("会话A")),
                10,
                100,
                50);
        List<ConversationMessage> second = window.trim(
                "1:session-b",
                List.of(ConversationMessage.user("会话B")),
                10,
                100,
                50);

        assertTrue(first.stream().anyMatch(message -> message.content().contains("会话A")));
        assertFalse(second.stream().anyMatch(message -> message.content().contains("会话A")));
        assertTrue(second.stream().anyMatch(message -> message.content().contains("会话B")));
    }

    @Test
    void shouldBoundSingleMessageBeforeApplyingTokenWindow() {
        List<ConversationMessage> result = window.trim(
                "1:session-a",
                List.of(ConversationMessage.assistant("这是一个非常长的回答内容")),
                10,
                10,
                6);

        assertEquals(1, result.size());
        assertTrue(estimator.estimateTokenCountInText(result.get(0).content()) <= 6);
    }
}
