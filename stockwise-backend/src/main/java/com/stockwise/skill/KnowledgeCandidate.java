package com.stockwise.skill;

import java.util.List;

/**
 * 候选知识：从一次已解决的对话中抽取、待用户确认后入库的知识条目（Step 11）。
 *
 * @param content    知识正文
 * @param tags       分类标签，供检索过滤与去重
 * @param confidence 置信度 0-100，低于 50 不予入库
 */
public record KnowledgeCandidate(
        String content,
        List<String> tags,
        Integer confidence
) {
}
