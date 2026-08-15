package com.bdlh.runtime.llm;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

/**
 * 使用可配置模型生成普通问答和外部资料总结，默认统一走DeepSeek。
 */
@Service
public class LocalAnswerClient {

    private static final String DEFAULT_CONCISE_OUTPUT = """
            \n\n输出长度要求（除非用户明确要求“详细展开”）：
            - 先用一句话直接回答核心问题。
            - 最多列出 3 条关键依据，每条只说一个事实或判断。
            - 正文控制在 300 个中文字符以内；不要复述提问，不要堆叠背景、链接或重复免责声明。
            - 信息不够时，只说明最关键的缺口，不要用泛泛的常识补成长文。
            """;

    private final ChatClient chatClient;

    public LocalAnswerClient(@Qualifier("generalChatClient") ChatClient chatClient) {
        this.chatClient = chatClient;
    }

    /**
     * 流式生成本地回答，供 Agent 复用现有 SSE 输出。
     */
    public Flux<String> streamChat(String systemPrompt, String userMessage) {
        return chatClient.prompt()
                .system(systemPrompt + DEFAULT_CONCISE_OUTPUT)
                .user(userMessage)
                .stream()
                .content();
    }

    /**
     * 同步生成结构化抽取结果，替代隐藏的二次付费调用。
     */
    public String call(String systemPrompt, String userMessage) {
        return chatClient.prompt()
                .system(systemPrompt + DEFAULT_CONCISE_OUTPUT)
                .user(userMessage)
                .call()
                .content();
    }
}
