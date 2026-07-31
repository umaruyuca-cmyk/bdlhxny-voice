package com.stockwise.llm;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

/**
 * 使用可配置模型生成普通问答和外部资料总结，默认统一走DeepSeek。
 */
@Service
public class LocalAnswerClient {

    private final ChatClient chatClient;

    public LocalAnswerClient(@Qualifier("generalChatClient") ChatClient chatClient) {
        this.chatClient = chatClient;
    }

    /**
     * 流式生成本地回答，供 Agent 复用现有 SSE 输出。
     */
    public Flux<String> streamChat(String systemPrompt, String userMessage) {
        return chatClient.prompt()
                .system(systemPrompt)
                .user(userMessage)
                .stream()
                .content();
    }

    /**
     * 同步生成结构化抽取结果，替代隐藏的二次付费调用。
     */
    public String call(String systemPrompt, String userMessage) {
        return chatClient.prompt()
                .system(systemPrompt)
                .user(userMessage)
                .call()
                .content();
    }
}
