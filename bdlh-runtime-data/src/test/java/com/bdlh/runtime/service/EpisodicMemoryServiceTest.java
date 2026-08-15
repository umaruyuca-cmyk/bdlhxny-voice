package com.bdlh.runtime.service;

import com.bdlh.runtime.config.EpisodicMemoryProperties;
import com.bdlh.runtime.entity.ConversationHistory;
import com.bdlh.runtime.llm.EmbeddingService;
import com.bdlh.runtime.memory.ConversationMessage;
import dev.langchain4j.data.segment.TextSegment;
import dev.langchain4j.store.embedding.EmbeddingSearchResult;
import dev.langchain4j.store.embedding.EmbeddingStore;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证完整会话归档优先于向量索引，并确保向量故障时长期记忆可安全降级。
 */
class EpisodicMemoryServiceTest {

    private final ConversationHistoryService historyService =
            mock(ConversationHistoryService.class);
    private final EmbeddingService embeddingService = mock(EmbeddingService.class);
    @SuppressWarnings("unchecked")
    private final EmbeddingStore<TextSegment> embeddingStore = mock(EmbeddingStore.class);
    private final EpisodicMemoryProperties properties = new EpisodicMemoryProperties();
    private final EpisodicMemoryService service = new EpisodicMemoryService(
            historyService, embeddingService, embeddingStore, properties);

    @Test
    void shouldArchiveRawConversationBeforeIndexing() {
        ConversationHistory history = history(21L, "摘要");
        when(historyService.archive(any(), anyString(), any(), anyString())).thenReturn(history);
        when(embeddingService.embed("摘要")).thenReturn(new float[]{0.1f, 0.2f});

        service.archive(
                7L,
                "session-1",
                "600519",
                List.of(ConversationMessage.user("问题")),
                "摘要");

        verify(historyService).archive(any(), anyString(), any(), anyString());
        verify(embeddingStore).add(any(), any(TextSegment.class));
    }

    @Test
    void shouldKeepRawArchiveWhenEmbeddingFails() {
        ConversationHistory history = history(22L, "摘要");
        when(historyService.archive(any(), anyString(), any(), anyString())).thenReturn(history);
        when(embeddingService.embed("摘要")).thenThrow(new IllegalStateException("Ollama unavailable"));

        assertDoesNotThrow(() -> service.archive(
                7L,
                "session-2",
                null,
                List.of(ConversationMessage.user("问题")),
                "摘要"));

        verify(historyService).archive(any(), anyString(), any(), anyString());
    }

    @Test
    void shouldFallbackToRecentSummariesWhenVectorSearchFails() {
        when(embeddingService.embed("继续上次的问题"))
                .thenThrow(new IllegalStateException("Ollama unavailable"));
        when(historyService.loadRecent(7L, 3))
                .thenReturn(List.of(history(2L, "较新摘要"), history(1L, "较早摘要")));

        List<String> summaries = service.loadRelevantSummaries(
                7L, "继续上次的问题", null);

        assertEquals(List.of("较早摘要", "较新摘要"), summaries);
    }

    @Test
    void shouldFallbackForLegacyArchivesWithoutVectorMatches() {
        when(embeddingService.embed("旧会话问题")).thenReturn(new float[]{0.1f});
        when(embeddingStore.search(any())).thenReturn(new EmbeddingSearchResult<>(List.of()));
        when(historyService.loadRecent(7L, 3))
                .thenReturn(List.of(history(2L, "较新摘要"), history(1L, "较早摘要")));

        List<String> summaries = service.loadRelevantSummaries(7L, "旧会话问题", null);

        assertEquals(List.of("较早摘要", "较新摘要"), summaries);
    }

    private ConversationHistory history(Long id, String summary) {
        ConversationHistory history = new ConversationHistory();
        history.setId(id);
        history.setSummary(summary);
        return history;
    }
}
