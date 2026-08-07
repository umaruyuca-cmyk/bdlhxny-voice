package com.stockwise.agent.react;

import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 将项目现有的 Spring AI 模型连接到 LangChain4j 的 ChatModel 协议，
 * 使 ReAct 规划使用统一的 LangChain4j 消息模型，同时沿用既有的模型切换配置。
 */
@Component
public class SpringAiLangChain4jChatModel implements ChatModel {

    private final ChatClient chatClient;

    public SpringAiLangChain4jChatModel(@Qualifier("generalChatClient") ChatClient chatClient) {
        this.chatClient = chatClient;
    }

    /**
     * 将 LangChain4j 的系统消息与用户消息映射到现有 ChatClient，供受控规划器同步取得下一步决策。
     */
    @Override
    public ChatResponse doChat(ChatRequest request) {
        List<ChatMessage> messages = request.messages();
        String system = messages.stream()
                .filter(SystemMessage.class::isInstance)
                .map(SystemMessage.class::cast)
                .map(SystemMessage::text)
                .reduce("", (left, right) -> left + "\n" + right)
                .trim();
        String user = messages.stream()
                .filter(UserMessage.class::isInstance)
                .map(UserMessage.class::cast)
                .map(UserMessage::singleText)
                .reduce("", (left, right) -> left + "\n" + right)
                .trim();
        String answer = chatClient.prompt()
                .system(system)
                .user(user)
                .call()
                .content();
        return ChatResponse.builder()
                .aiMessage(AiMessage.from(answer == null ? "" : answer))
                .build();
    }
}
