package com.bdlh.runtime.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.bdlh.runtime.llm.LocalAnswerClient;
import com.bdlh.runtime.skill.KnowledgeCandidate;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 候选知识抽取器，实现 PRD Step 11。
 * 从一次已解决的投资问答中提取可长期沉淀的知识点，输出结构化候选供用户确认。
 */
@Service
public class KnowledgeExtractor {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final LocalAnswerClient localAnswerClient;

    public KnowledgeExtractor(LocalAnswerClient localAnswerClient) {
        this.localAnswerClient = localAnswerClient;
    }

    /**
     * 抽取候选知识；模型输出不稳或无知识点时返回空列表，绝不抛异常阻塞主流程。
     */
    public List<KnowledgeCandidate> extract(String question, String answer) {
        // 1. 让本地模型输出 JSON 候选数组，避免解决后产生隐藏付费调用
        String raw = localAnswerClient.call(systemPrompt(), userPayload(question, answer));
        // 2. 解析 JSON 数组为候选列表
        return parse(raw);
    }

    private String systemPrompt() {
        return """
                你是知识抽取器。从一次已解决的投资问答中提取值得长期沉淀的知识点。
                只输出 JSON 数组，格式：[{"content":"知识点","tags":["标签"],"confidence":85}]
                content 须是自足的知识陈述（不依赖原对话上下文也能读懂），confidence 取 0-100。
                没有可沉淀知识时输出 []。不要输出 JSON 以外的文字。
                """;
    }

    private String userPayload(String question, String answer) {
        return "用户问题：" + question + "\n\n回答：\n" + answer;
    }

    private List<KnowledgeCandidate> parse(String raw) {
        // 1. 截取首个 JSON 数组（模型可能输出多余文字）
        if (raw == null) {
            return List.of();
        }
        int start = raw.indexOf('[');
        int end = raw.lastIndexOf(']');
        if (start < 0 || end <= start) {
            return List.of();
        }
        String json = raw.substring(start, end + 1);
        try {
            // 2. 解析数组并逐项映射为候选
            List<Object> items = MAPPER.readValue(json, List.class);
            List<KnowledgeCandidate> result = new ArrayList<>();
            for (Object item : items) {
                if (item instanceof Map<?, ?> m) {
                    Object contentObj = m.get("content");
                    String content = contentObj == null ? "" : String.valueOf(contentObj);
                    if (content.isBlank()) {
                        continue;
                    }
                    result.add(new KnowledgeCandidate(content, toStringList(m.get("tags")), toInt(m.get("confidence"))));
                }
            }
            return result;
        } catch (Exception e) {
            return List.of();
        }
    }

    /**
     * 把 JSON 里的 tags 节点安全转为字符串列表，兼容非数组输入。
     */
    private List<String> toStringList(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> result = new ArrayList<>();
        for (Object o : list) {
            result.add(String.valueOf(o));
        }
        return result;
    }

    private Integer toInt(Object o) {
        if (o instanceof Number n) {
            return n.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(o));
        } catch (Exception e) {
            return null;
        }
    }
}
