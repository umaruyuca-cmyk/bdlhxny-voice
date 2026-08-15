package com.bdlh.runtime.memory;

import com.bdlh.runtime.config.EpisodicMemoryProperties;
import com.bdlh.runtime.entity.ConversationEpisodeEmbedding;
import com.bdlh.runtime.llm.EmbeddingService;
import com.bdlh.runtime.mapper.ConversationEpisodeEmbeddingMapper;
import dev.langchain4j.data.document.Metadata;
import dev.langchain4j.data.embedding.Embedding;
import dev.langchain4j.data.segment.TextSegment;
import dev.langchain4j.store.embedding.EmbeddingSearchRequest;
import dev.langchain4j.store.embedding.filter.comparison.IsEqualTo;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证 LangChain4j 情景记忆适配器的领域元数据映射和强制用户隔离。
 */
class LangChainEpisodicEmbeddingStoreTest {

    private final ConversationEpisodeEmbeddingMapper mapper =
            mock(ConversationEpisodeEmbeddingMapper.class);
    private final EmbeddingService embeddingService = mock(EmbeddingService.class);
    private final EpisodicMemoryProperties properties = new EpisodicMemoryProperties();
    private final LangChainEpisodicEmbeddingStore store =
            new LangChainEpisodicEmbeddingStore(mapper, embeddingService, properties);

    @Test
    void shouldPersistTextSegmentWithRequiredDomainMetadata() {
        when(mapper.upsertEpisode(any())).thenReturn(1);
        Metadata metadata = new Metadata()
                .put(LangChainEpisodicEmbeddingStore.META_HISTORY_ID, 12L)
                .put(LangChainEpisodicEmbeddingStore.META_USER_ID, 7L)
                .put(LangChainEpisodicEmbeddingStore.META_SESSION_ID, "session-1")
                .put(LangChainEpisodicEmbeddingStore.META_SYMBOL, "600519");

        store.add(Embedding.from(new float[]{0.1f, 0.2f}),
                TextSegment.from("历史摘要", metadata));

        ArgumentCaptor<ConversationEpisodeEmbedding> captor =
                ArgumentCaptor.forClass(ConversationEpisodeEmbedding.class);
        verify(mapper).upsertEpisode(captor.capture());
        ConversationEpisodeEmbedding saved = captor.getValue();
        assertEquals(12L, saved.getConversationHistoryId());
        assertEquals(7L, saved.getUserId());
        assertEquals("session-1", saved.getSessionId());
        assertEquals("600519", saved.getSymbol());
        assertEquals("历史摘要", saved.getContent());
    }

    @Test
    void shouldRejectSearchWithoutUserFilter() {
        EmbeddingSearchRequest request = EmbeddingSearchRequest.builder()
                .queryEmbedding(Embedding.from(new float[]{0.1f}))
                .maxResults(3)
                .minScore(0.5)
                .build();

        assertThrows(IllegalArgumentException.class, () -> store.search(request));
    }

    @Test
    void shouldSearchWithinUserScope() {
        when(embeddingService.toVectorString(any())).thenReturn("[0.1]");
        when(mapper.searchRelevant(
                anyString(), anyLong(), isNull(), anyInt(), anyInt(),
                anyDouble(), anyDouble(), anyDouble(), anyInt()))
                .thenReturn(List.of());
        EmbeddingSearchRequest request = EmbeddingSearchRequest.builder()
                .queryEmbedding(Embedding.from(new float[]{0.1f}))
                .maxResults(3)
                .minScore(0.5)
                .filter(new IsEqualTo(LangChainEpisodicEmbeddingStore.META_USER_ID, 7L))
                .build();

        store.search(request);

        verify(mapper).searchRelevant(
                "[0.1]", 7L, null, 3, 12,
                0.5, 0.85, 0.15, 30);
    }
}
