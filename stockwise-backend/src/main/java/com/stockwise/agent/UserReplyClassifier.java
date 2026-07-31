package com.stockwise.agent;

import com.stockwise.memory.FeedbackType;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 识别暂停点中的确认与否定回复，优先判断否定表达。
 * 这样可避免“没有解决”因包含“解决”而被误判为肯定。
 */
@Component
public class UserReplyClassifier {

    private static final List<String> NEGATIVE = List.of(
            "没有", "没解决", "未解决", "不可以", "不对", "不同意", "拒绝", "取消", "否", "no"
    );
    private static final List<String> RESOLVED = List.of(
            "已解决", "已经解决", "解决了", "好了", "可以", "对的", "yes"
    );
    private static final List<String> CONFIRMED = List.of(
            "确认", "入库", "同意", "yes"
    );

    /**
     * 判断用户是否明确表示问题已经解决。
     */
    public boolean isResolved(String message) {
        return matchesPositive(message, RESOLVED);
    }

    /**
     * 判断用户是否明确确认知识入库。
     */
    public boolean isConfirmed(String message) {
        return matchesPositive(message, CONFIRMED);
    }

    /**
     * 将解决阶段回复分类为可持久化反馈，补充说明与明确否定分开统计。
     */
    public FeedbackType classifyResolution(String message) {
        if (isResolved(message)) {
            return FeedbackType.RESOLVED;
        }
        return containsNegative(message) ? FeedbackType.UNRESOLVED : FeedbackType.CORRECTION;
    }

    /**
     * 将知识确认阶段回复分类为确认或拒绝。
     */
    public FeedbackType classifyKnowledgeConfirmation(String message) {
        return isConfirmed(message)
                ? FeedbackType.KNOWLEDGE_CONFIRMED
                : FeedbackType.KNOWLEDGE_REJECTED;
    }

    private boolean matchesPositive(String message, List<String> positives) {
        String normalized = message == null ? "" : message.trim().toLowerCase();
        for (String negative : NEGATIVE) {
            if (normalized.contains(negative)) {
                return false;
            }
        }
        for (String positive : positives) {
            if (normalized.contains(positive)) {
                return true;
            }
        }
        return false;
    }

    private boolean containsNegative(String message) {
        String normalized = message == null ? "" : message.trim().toLowerCase();
        return NEGATIVE.stream().anyMatch(normalized::contains);
    }
}
