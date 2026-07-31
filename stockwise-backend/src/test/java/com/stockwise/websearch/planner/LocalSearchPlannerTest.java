package com.stockwise.websearch.planner;

import com.stockwise.agent.routing.ModelPolicy;
import com.stockwise.agent.routing.RequestRoute;
import com.stockwise.agent.routing.RouteDecision;
import com.stockwise.llm.ChatIntent;
import com.stockwise.websearch.model.SearchTask;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 验证本地搜索编排只产生最小任务，不发送完整对话和用户私有字段。
 */
class LocalSearchPlannerTest {

    private final LocalSearchPlanner planner = new LocalSearchPlanner();

    @Test
    void externalResearchRemovesConversationAndPrivateData() {
        String question = "请帮我查一下最近的新能源政策有哪些，我的成本是12.34，告诉我是否利好";
        List<SearchTask> tasks = planner.plan(externalDecision(), question);

        assertThat(tasks).hasSize(1);
        assertThat(tasks.get(0).query())
                .isNotEqualTo(question)
                .doesNotContain("我的成本", "12.34", "帮我", "告诉我")
                .contains("新能源政策", "最新", "政策", "官方");
    }

    @Test
    void causalSearchUsesFixedSymbolDirectionQuery() {
        String question = "600519今天为什么大跌？我的持仓成本是1800";
        List<SearchTask> tasks = planner.plan(causalDecision(), question);

        assertThat(tasks.get(0).query())
                .isEqualTo("600519 近期 下跌 原因 新闻 公告")
                .doesNotContain("1800", "持仓");
    }

    private RouteDecision externalDecision() {
        return new RouteDecision(
                RequestRoute.EXTERNAL_RESEARCH,
                ChatIntent.INVESTMENT_QA,
                ModelPolicy.LOCAL_ONLY,
                null,
                "TEST",
                1.0,
                false,
                true,
                false,
                null);
    }

    private RouteDecision causalDecision() {
        return new RouteDecision(
                RequestRoute.MARKET_CAUSAL_ANALYSIS,
                ChatIntent.STOCK_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
                "600519",
                "TEST",
                1.0,
                true,
                true,
                false,
                null);
    }
}
