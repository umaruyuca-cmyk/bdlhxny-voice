package com.stockwise.llm;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

/**
 * 问题意图分类服务，默认使用DeepSeek并保留Ollama回退能力。
 * 只做分类不做推理，模型输出必须容错，绝不抛异常阻塞主流程。
 */
@Service
public class IntentClassifier {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final ChatClient chatClient;

    public IntentClassifier(@Qualifier("generalChatClient") ChatClient chatClient) {
        this.chatClient = chatClient;
    }

    /**
     * 对用户问题做意图分类，最多重试一次，两次都解析失败则回退 GENERAL_CHAT。
     */
    public ChatIntent classify(String question) {
        for (int attempt = 1; attempt <= 2; attempt++) {
            // 1. 调小模型，强约束只输出一行 JSON
            String raw = chatClient.prompt()
                    .system(systemPrompt())
                    .user(question)
                    .call()
                    .content();
            // 2. 解析意图，成功即返回
            ChatIntent parsed = parse(raw);
            if (parsed != null) {
                return parsed;
            }
        }
        // 3. 两次都失败，安全兜底为闲聊，保证主流程不中断
        return ChatIntent.GENERAL_CHAT;
    }

    /**
     * 分类系统指令，锁定输出格式与四类取值。
     */
    private String systemPrompt() {
        return """
                你是问题分类器，只输出一行 JSON，格式严格为：{"intent":"X"}
                X 取值四选一：
                investment_qa —— 投资知识问答（术语、策略、政策）
                portfolio_analysis —— 持仓组合分析
                stock_analysis —— 单标的深度分析
                general_chat —— 其他闲聊
                不要输出 JSON 以外的任何文字。
                """;
    }

    /**
     * 从模型输出中解析 intent 字段，容忍前后多余文字；解析失败返回 null。
     */
    private ChatIntent parse(String raw) {
        if (raw == null) {
            return null;
        }
        // 1. 截取首个 JSON 对象（小模型可能输出多余解释）
        int start = raw.indexOf('{');
        int end = raw.lastIndexOf('}');
        if (start < 0 || end <= start) {
            return null;
        }
        String json = raw.substring(start, end + 1);
        try {
            // 2. 提取 intent 字段并映射为枚举
            String intent = MAPPER.readTree(json).path("intent").asText("");
            return map(intent);
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 把模型返回的意图字符串映射为枚举；无法识别时返回 null（触发重试或兜底）。
     */
    private ChatIntent map(String intent) {
        if (intent == null) {
            return null;
        }
        return switch (intent.trim().toLowerCase()) {
            case "investment_qa" -> ChatIntent.INVESTMENT_QA;
            case "portfolio_analysis" -> ChatIntent.PORTFOLIO_ANALYSIS;
            case "stock_analysis" -> ChatIntent.STOCK_ANALYSIS;
            case "general_chat" -> ChatIntent.GENERAL_CHAT;
            default -> null;
        };
    }
}
