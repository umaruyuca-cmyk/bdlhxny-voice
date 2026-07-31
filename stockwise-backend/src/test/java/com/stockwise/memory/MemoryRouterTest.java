package com.stockwise.memory;

import com.stockwise.service.EpisodicMemoryService;
import com.stockwise.service.KnowledgeIngestService;
import com.stockwise.service.UserFeedbackService;
import com.stockwise.service.UserPortfolioService;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;

/**
 * 验证每类记忆载荷只能进入固定存储，防止业务组件混用 Redis、PG 和 PgVector。
 */
class MemoryRouterTest {

    private final MemoryRouter router = new MemoryRouter(
            mock(SessionStateService.class),
            mock(EpisodicMemoryService.class),
            mock(KnowledgeIngestService.class),
            mock(UserFeedbackService.class),
            mock(UserPortfolioService.class));

    @Test
    void shouldRouteAllPayloadTypesToFixedDestinations() {
        assertEquals(MemoryDestination.WORKING_REDIS,
                router.destination(MemoryPayloadType.SESSION_STATE));
        assertEquals(MemoryDestination.EPISODIC_POSTGRES,
                router.destination(MemoryPayloadType.CONVERSATION_ARCHIVE));
        assertEquals(MemoryDestination.EPISODIC_POSTGRES,
                router.destination(MemoryPayloadType.AGENT_RUN));
        assertEquals(MemoryDestination.EPISODIC_POSTGRES,
                router.destination(MemoryPayloadType.USER_FEEDBACK));
        assertEquals(MemoryDestination.SEMANTIC_PGVECTOR,
                router.destination(MemoryPayloadType.CONFIRMED_KNOWLEDGE));
        assertEquals(MemoryDestination.BUSINESS_POSTGRES,
                router.destination(MemoryPayloadType.PORTFOLIO_POSITION));
        assertEquals(MemoryDestination.BUSINESS_POSTGRES,
                router.destination(MemoryPayloadType.USER_FINANCIAL_CONFIG));
    }
}
