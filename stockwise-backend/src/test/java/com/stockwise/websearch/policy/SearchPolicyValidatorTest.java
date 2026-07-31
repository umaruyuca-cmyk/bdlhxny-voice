package com.stockwise.websearch.policy;

import com.stockwise.websearch.model.SearchPurpose;
import com.stockwise.websearch.model.SearchTask;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * 验证外部搜索前的隐私字段和资源预算校验。
 */
class SearchPolicyValidatorTest {

    private final SearchPolicyValidator validator = new SearchPolicyValidator();

    @Test
    void acceptsMinimalPublicQuery() {
        List<SearchTask> tasks = validator.validate(List.of(new SearchTask(
                "task-1", SearchPurpose.POLICY_UPDATE, "证券交易印花税 最新政策",
                null, 365, List.of("gov.cn"), 5)));

        assertEquals(1, tasks.size());
    }

    @Test
    void rejectsPrivateCostInQuery() {
        assertThrows(IllegalArgumentException.class, () -> validator.validate(List.of(new SearchTask(
                "task-1", SearchPurpose.NEWS_CATALYST, "我的成本1200 贵州茅台新闻",
                "600519", 30, List.of(), 5))));
    }
}
