package com.bdlh.runtime.agent.context;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证保守 Token 估算和 Unicode 安全截断。
 */
class ConservativeTokenCountEstimatorTest {

    private final ConservativeTokenCountEstimator estimator = new ConservativeTokenCountEstimator();

    @Test
    void shouldCountChineseMoreConservativelyThanAscii() {
        assertTrue(estimator.estimateTokenCountInText("中文测试")
                > estimator.estimateTokenCountInText("test"));
    }

    @Test
    void shouldTruncateWithoutSplittingEmoji() {
        String result = estimator.truncateToTokens("分析📈走势和风险", 5);

        assertFalse(result.contains("\uD83D") && !result.contains("📈"));
        assertTrue(estimator.estimateTokenCountInText(result) <= 5);
    }
}
