package com.stockwise.agent;

import com.stockwise.memory.FeedbackType;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证暂停点回复先识别否定语义，避免字符串包含导致状态误跳转。
 */
class UserReplyClassifierTest {

    private final UserReplyClassifier classifier = new UserReplyClassifier();

    @Test
    void shouldRejectNegativeResolutionPhrases() {
        assertFalse(classifier.isResolved("没有解决，还需要分析"));
        assertFalse(classifier.isResolved("不可以"));
        assertFalse(classifier.isResolved("no"));
    }

    @Test
    void shouldAcceptExplicitResolutionPhrases() {
        assertTrue(classifier.isResolved("已经解决了"));
        assertTrue(classifier.isResolved("可以"));
    }

    @Test
    void shouldDistinguishConfirmationFromRejection() {
        assertTrue(classifier.isConfirmed("确认入库"));
        assertFalse(classifier.isConfirmed("不同意入库"));
        assertFalse(classifier.isConfirmed("拒绝"));
    }

    @Test
    void shouldClassifyStructuredFeedbackTypes() {
        assertEquals(FeedbackType.RESOLVED, classifier.classifyResolution("已经解决"));
        assertEquals(FeedbackType.UNRESOLVED, classifier.classifyResolution("没有解决"));
        assertEquals(FeedbackType.CORRECTION, classifier.classifyResolution("我的预算改成 3000"));
        assertEquals(FeedbackType.KNOWLEDGE_CONFIRMED,
                classifier.classifyKnowledgeConfirmation("确认入库"));
        assertEquals(FeedbackType.KNOWLEDGE_REJECTED,
                classifier.classifyKnowledgeConfirmation("拒绝"));
    }
}
