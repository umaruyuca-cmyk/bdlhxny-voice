package com.stockwise.agent.context;

import com.stockwise.memory.ConversationMessage;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.memory.ChatMemory;
import dev.langchain4j.memory.chat.TokenWindowChatMemory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 使用 LangChain4j 为单次请求创建隔离的 Token 窗口，只裁剪上下文视图而不接管 Redis 或 PG 持久化。
 */
@Component
public class LangChainContextWindow {

    private final ConservativeTokenCountEstimator tokenEstimator;

    public LangChainContextWindow(ConservativeTokenCountEstimator tokenEstimator) {
        this.tokenEstimator = tokenEstimator;
    }

    /**
     * 先按消息数截取，再按 Token 淘汰旧消息，返回可安全注入本轮 Prompt 的最近消息。
     */
    public List<ConversationMessage> trim(String memoryId,
                                          List<ConversationMessage> messages,
                                          int maxMessages,
                                          int maxTokens,
                                          int maxMessageTokens) {
        if (messages == null || messages.isEmpty() || maxMessages <= 0 || maxTokens <= 0) {
            return List.of();
        }
        int start = Math.max(0, messages.size() - maxMessages);
        ChatMemory memory = TokenWindowChatMemory.builder()
                .id(memoryId)
                .maxTokens(maxTokens, tokenEstimator)
                .build();
        // 1. 每次请求创建独立窗口，避免不同 session 共享 ChatMemory。
        for (int i = start; i < messages.size(); i++) {
            ConversationMessage bounded = boundMessage(messages.get(i), maxMessageTokens);
            ChatMessage chatMessage = toChatMessage(bounded);
            if (chatMessage != null) {
                memory.add(chatMessage);
            }
        }
        // 2. 仅把裁剪结果还原为工作记忆消息，不向 LangChain4j Store 持久化。
        List<ConversationMessage> result = new ArrayList<>();
        for (ChatMessage chatMessage : memory.messages()) {
            ConversationMessage message = fromChatMessage(chatMessage);
            if (message != null) {
                result.add(message);
            }
        }
        return List.copyOf(result);
    }

    private ConversationMessage boundMessage(ConversationMessage message, int maxMessageTokens) {
        if (message == null) {
            return null;
        }
        String content = tokenEstimator.truncateToTokens(message.content(), maxMessageTokens);
        return new ConversationMessage(message.role(), content);
    }

    private ChatMessage toChatMessage(ConversationMessage message) {
        if (message == null || message.content().isBlank()) {
            return null;
        }
        if ("assistant".equals(message.role())) {
            return AiMessage.from(message.content());
        }
        return UserMessage.from(message.content());
    }

    private ConversationMessage fromChatMessage(ChatMessage message) {
        if (message instanceof UserMessage userMessage && userMessage.hasSingleText()) {
            return ConversationMessage.user(userMessage.singleText());
        }
        if (message instanceof AiMessage aiMessage) {
            return ConversationMessage.assistant(aiMessage.text());
        }
        return null;
    }
}
