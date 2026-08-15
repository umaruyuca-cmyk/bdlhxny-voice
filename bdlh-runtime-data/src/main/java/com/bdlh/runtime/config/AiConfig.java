package com.bdlh.runtime.config;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.ollama.OllamaChatModel;
import org.springframework.ai.ollama.api.OllamaApi;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 构建DeepSeek、Ollama及可切换的通用ChatClient。
 * 项目保留Ollama回退能力，默认由DeepSeek统一承担聊天和分类。
 */
@Configuration
public class AiConfig {

    private static final String OLLAMA_API_KEY_HEADER = "x-ollama-api-key";

    /**
     * 创建支持云端网关API Key鉴权的Ollama客户端。
     */
    @Bean
    public OllamaApi ollamaApi(
            @Value("${spring.ai.ollama.base-url}") String baseUrl,
            @Value("${spring.ai.ollama.api-key:}") String apiKey) {
        RestClient.Builder restClientBuilder = RestClient.builder();
        WebClient.Builder webClientBuilder = WebClient.builder();
        // 1. 配置了API Key时，同时为同步与流式请求添加网关鉴权头。
        if (StringUtils.hasText(apiKey)) {
            restClientBuilder.defaultHeader(OLLAMA_API_KEY_HEADER, apiKey);
            webClientBuilder.defaultHeader(OLLAMA_API_KEY_HEADER, apiKey);
        }
        return OllamaApi.builder()
                .baseUrl(baseUrl)
                .restClientBuilder(restClientBuilder)
                .webClientBuilder(webClientBuilder)
                .build();
    }

    @Bean("deepSeekChatClient")
    public ChatClient deepSeekChatClient(OpenAiChatModel openAiChatModel) {
        return ChatClient.builder(openAiChatModel).build();
    }

    @Bean("ollamaChatClient")
    public ChatClient ollamaChatClient(OllamaChatModel ollamaChatModel) {
        return ChatClient.builder(ollamaChatModel).build();
    }

    /**
     * 根据配置选择普通回答与旧意图分类共用的模型客户端。
     */
    @Bean("generalChatClient")
    public ChatClient generalChatClient(
            @Value("${bdlh_runtime.ai.chat-provider:deepseek}") String provider,
            @Qualifier("deepSeekChatClient") ChatClient deepSeekChatClient,
            @Qualifier("ollamaChatClient") ChatClient ollamaChatClient) {
        // 1. 仅显式选择ollama时回退本地模型，其余情况统一使用DeepSeek。
        return "ollama".equalsIgnoreCase(provider) ? ollamaChatClient : deepSeekChatClient;
    }
}
