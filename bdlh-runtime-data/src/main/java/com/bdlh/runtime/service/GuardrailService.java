package com.bdlh.runtime.service;

import com.bdlh.runtime.dto.GuardrailResult;
import com.bdlh.runtime.skill.KnowledgeCandidate;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 分层护栏，实现 PRD 第 10 章的输入/输出/入库三道安全检查。
 * 检索层护栏（过期/冲突/低可信）由 KnowledgeFilter 负责，本服务只管另外三层。
 */
@Service
public class GuardrailService {

    /** Prompt 注入特征词，命中即拦截输入。 */
    private static final List<String> INJECTION_PATTERNS = List.of(
            "忽略以上", "忽略上面", "忽略之前的指令", "ignore previous", "ignore above",
            "你现在是", "你的新角色", "重新设定", "不要遵守", "system:"
    );

    /** 禁止的承诺收益类措辞，输出与入库均不得出现。 */
    private static final List<String> FORBIDDEN_PHRASES = List.of(
            "保证收益", "稳赚", "百分百", "一定会涨", "一定赚钱", "无风险", "零风险", "包赚", "绝对盈利"
    );

    /** 入库最小内容长度，低于此值视为无价值知识。 */
    private static final int MIN_CONTENT_LENGTH = 20;

    /**
     * 输入护栏（Step 1）：检测空消息与 Prompt 注入。
     */
    public GuardrailResult checkInput(String message) {
        // 1. 空消息直接拒
        if (message == null || message.isBlank()) {
            return new GuardrailResult(false, "空消息");
        }
        // 2. 命中注入特征词即拦截
        String lower = message.toLowerCase();
        for (String p : INJECTION_PATTERNS) {
            if (lower.contains(p.toLowerCase())) {
                return new GuardrailResult(false, "疑似 Prompt 注入: " + p);
            }
        }
        return new GuardrailResult(true, null);
    }

    /**
     * 输出护栏（Step 8）：检测承诺收益类禁止措辞。
     */
    public GuardrailResult checkOutput(String text) {
        if (text == null) {
            return new GuardrailResult(true, null);
        }
        for (String p : FORBIDDEN_PHRASES) {
            if (text.contains(p)) {
                return new GuardrailResult(false, "命中禁止措辞: " + p);
            }
        }
        return new GuardrailResult(true, null);
    }

    /**
     * 入库护栏（Step 11）：内容长度门槛 + 禁止措辞；置信度门槛由 IngestService 把关。
     */
    public GuardrailResult checkKnowledge(KnowledgeCandidate candidate) {
        String content = candidate.content();
        // 1. 内容过短拒绝
        if (content == null || content.length() < MIN_CONTENT_LENGTH) {
            return new GuardrailResult(false, "内容过短(<" + MIN_CONTENT_LENGTH + "字)");
        }
        // 2. 命中禁止措辞拒绝
        for (String p : FORBIDDEN_PHRASES) {
            if (content.contains(p)) {
                return new GuardrailResult(false, "命中禁止措辞: " + p);
            }
        }
        return new GuardrailResult(true, null);
    }
}
