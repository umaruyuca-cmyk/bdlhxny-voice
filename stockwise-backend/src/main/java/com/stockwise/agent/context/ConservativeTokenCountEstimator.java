package com.stockwise.agent.context;

import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.ToolExecutionResultMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.TokenCountEstimator;
import org.springframework.stereotype.Component;

/**
 * 为非 OpenAI 模型提供保守 Token 估算，避免错误复用 GPT tokenizer 导致上下文超限。
 * 中文及其他非 ASCII 字符按单字符估算，ASCII 文本按四字符估算，并为消息协议预留固定开销。
 */
@Component
public class ConservativeTokenCountEstimator implements TokenCountEstimator {

    private static final int MESSAGE_OVERHEAD_TOKENS = 4;
    private static final int ASCII_CHARS_PER_TOKEN = 4;

    /**
     * 估算普通文本的 Token 数，结果用于窗口控制而非计费。
     */
    @Override
    public int estimateTokenCountInText(String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        int tokens = 0;
        int asciiCharacters = 0;
        for (int offset = 0; offset < text.length(); ) {
            int codePoint = text.codePointAt(offset);
            offset += Character.charCount(codePoint);
            if (codePoint <= 0x7F) {
                asciiCharacters++;
            } else {
                tokens++;
            }
        }
        return tokens + divideRoundingUp(asciiCharacters, ASCII_CHARS_PER_TOKEN);
    }

    /**
     * 估算单条 LangChain4j 消息的 Token 数，并计入消息协议开销。
     */
    @Override
    public int estimateTokenCountInMessage(ChatMessage message) {
        if (message == null) {
            return 0;
        }
        return MESSAGE_OVERHEAD_TOKENS + estimateTokenCountInText(messageText(message));
    }

    /**
     * 汇总多条消息的 Token 估算。
     */
    @Override
    public int estimateTokenCountInMessages(Iterable<ChatMessage> messages) {
        if (messages == null) {
            return 0;
        }
        int total = 0;
        for (ChatMessage message : messages) {
            total += estimateTokenCountInMessage(message);
        }
        return total;
    }

    /**
     * 在不超过给定估算 Token 数的前提下截断文本。
     */
    public String truncateToTokens(String text, int maxTokens) {
        if (text == null || text.isEmpty() || maxTokens <= 0) {
            return "";
        }
        if (estimateTokenCountInText(text) <= maxTokens) {
            return text;
        }
        int contentBudget = Math.max(0, maxTokens - estimateTokenCountInText("…"));
        int end = 0;
        for (int offset = 0; offset < text.length(); ) {
            int next = offset + Character.charCount(text.codePointAt(offset));
            if (estimateTokenCountInText(text.substring(0, next)) > contentBudget) {
                break;
            }
            end = next;
            offset = next;
        }
        return text.substring(0, end).trim() + "…";
    }

    private String messageText(ChatMessage message) {
        if (message instanceof UserMessage userMessage && userMessage.hasSingleText()) {
            return userMessage.singleText();
        }
        if (message instanceof AiMessage aiMessage) {
            return aiMessage.text();
        }
        if (message instanceof SystemMessage systemMessage) {
            return systemMessage.text();
        }
        if (message instanceof ToolExecutionResultMessage toolMessage && toolMessage.hasSingleText()) {
            return toolMessage.text();
        }
        return message.toString();
    }

    private int divideRoundingUp(int value, int divisor) {
        return value == 0 ? 0 : (value + divisor - 1) / divisor;
    }

}
