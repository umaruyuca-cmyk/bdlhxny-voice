package com.bdlh.runtime.llm;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.ResponseFormat;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.List;
import java.util.Map;

/**
 * DeepSeek 深度推理客户端，走 Spring AI 的 OpenAI 兼容协议调用 deepseek-v4-pro。
 * 提供流式叙事（Step 7 推理）与同步调用（结构化抽取）两种模式，按 token 计费故需按需使用。
 */
@Service
class DeepSeekClient {

    private final ChatClient deepSeekChatClient;

    DeepSeekClient(@Qualifier("deepSeekChatClient") ChatClient deepSeekChatClient) {
        this.deepSeekChatClient = deepSeekChatClient;
    }

    /**
     * 流式叙事调用，逐 token 返回，供 Agent 转发为 SSE 推给前端。
     */
    public Flux<String> streamChat(String systemPrompt, String userMessage) {
        return deepSeekChatClient.prompt()
                .system(systemPrompt)
                .user(userMessage)
                .stream()
                .content();
    }

    /**
     * 带工具的流式调用（function calling）：仅注册 Skill 允许的 ToolCallback，并应用本次推理参数。
     */
    public Flux<String> streamChatWithTools(String systemPrompt,
                                            String userMessage,
                                            List<ToolCallback> toolCallbacks,
                                            Map<String, Object> constraints) {
        OpenAiChatOptions options = buildOptions(constraints);
        ChatClient.ChatClientRequestSpec request = deepSeekChatClient.prompt()
                .system(systemPrompt)
                .user(userMessage)
                .options(options);
        // 1. 空白名单时完全不注册工具，确保 general-chat 无法越权调用
        if (toolCallbacks != null && !toolCallbacks.isEmpty()) {
            request = request.toolCallbacks(toolCallbacks);
        }
        return request.stream().content();
    }

    /**
     * 同步调用，用于需要完整结果再解析的场景（SkillResult 抽取、候选知识提取）。
     */
    public String call(String systemPrompt, String userMessage) {
        return deepSeekChatClient.prompt()
                .system(systemPrompt)
                .user(userMessage)
                .call()
                .content();
    }

    /**
     * 使用固定 JSON 输出选项执行同步结构化调用，供包内受限分类服务使用。
     */
    public String callJson(String systemPrompt,
                           String userMessage,
                           String model,
                           int maxTokens) {
        OpenAiChatOptions.Builder options = OpenAiChatOptions.builder()
                .temperature(0.0)
                .maxTokens(maxTokens)
                .parallelToolCalls(false)
                .internalToolExecutionEnabled(false)
                .responseFormat(ResponseFormat.builder()
                        .type(ResponseFormat.Type.JSON_OBJECT)
                        .build());
        if (model != null && !model.isBlank()) {
            options.model(model.trim());
        }
        return deepSeekChatClient.prompt()
                .system(systemPrompt)
                .user(userMessage)
                .options(options.build())
                .call()
                .content();
    }

    /**
     * 将 Skill 中的通用约束映射为 OpenAI 兼容推理参数。
     */
    private OpenAiChatOptions buildOptions(Map<String, Object> constraints) {
        OpenAiChatOptions.Builder builder = OpenAiChatOptions.builder()
                .parallelToolCalls(false)
                .internalToolExecutionEnabled(true);
        if (constraints == null) {
            return builder.build();
        }
        // 1. 只接受数字类型，非法配置保持模型默认值
        Object temperature = constraints.get("temperature");
        if (temperature instanceof Number number) {
            builder.temperature(number.doubleValue());
        }
        Object maxTokens = constraints.get("maxTokens");
        if (maxTokens instanceof Number number) {
            builder.maxTokens(number.intValue());
        }
        return builder.build();
    }
}
