package com.bdlh.runtime.service;

import com.bdlh.runtime.config.EpisodicMemoryProperties;
import com.bdlh.runtime.entity.ConversationHistory;
import com.bdlh.runtime.llm.EmbeddingService;
import com.bdlh.runtime.memory.ConversationMessage;
import com.bdlh.runtime.memory.LangChainEpisodicEmbeddingStore;
import dev.langchain4j.data.document.Metadata;
import dev.langchain4j.data.embedding.Embedding;
import dev.langchain4j.data.segment.TextSegment;
import dev.langchain4j.store.embedding.EmbeddingMatch;
import dev.langchain4j.store.embedding.EmbeddingSearchRequest;
import dev.langchain4j.store.embedding.EmbeddingSearchResult;
import dev.langchain4j.store.embedding.EmbeddingStore;
import dev.langchain4j.store.embedding.filter.Filter;
import dev.langchain4j.store.embedding.filter.comparison.IsEqualTo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * 协调完整会话归档与 LangChain4j 情景向量索引，确保长期记忆可检索且索引故障不丢原始历史。
 */
@Service
public class EpisodicMemoryService {

    private static final Logger log = LoggerFactory.getLogger(EpisodicMemoryService.class);

    private final ConversationHistoryService conversationHistoryService;
    private final EmbeddingService embeddingService;
    private final EmbeddingStore<TextSegment> embeddingStore;
    private final EpisodicMemoryProperties properties;

    public EpisodicMemoryService(ConversationHistoryService conversationHistoryService,
                                 EmbeddingService embeddingService,
                                 EmbeddingStore<TextSegment> embeddingStore,
                                 EpisodicMemoryProperties properties) {
        this.conversationHistoryService = conversationHistoryService;
        this.embeddingService = embeddingService;
        this.embeddingStore = embeddingStore;
        this.properties = properties;
    }

    /**
     * 先保存完整会话，再尽力建立摘要向量索引，避免外部向量服务失败导致历史丢失。
     */
    public void archive(Long userId,
                        String sessionId,
                        String symbol,
                        List<ConversationMessage> messages,
                        String summary) {
        // 1. 完整归档必须先成功，后续索引属于可重建的派生数据。
        ConversationHistory history = conversationHistoryService.archive(
                userId, sessionId, messages, summary);
        if (!properties.isEnabled() || summary == null || summary.isBlank()) {
            return;
        }
        try {
            // 2. 复用现有 Spring AI Embedding 客户端，只把数据模型交给 LangChain4j。
            Metadata metadata = new Metadata()
                    .put(LangChainEpisodicEmbeddingStore.META_HISTORY_ID, history.getId())
                    .put(LangChainEpisodicEmbeddingStore.META_USER_ID, userId)
                    .put(LangChainEpisodicEmbeddingStore.META_SESSION_ID, sessionId)
                    .put(LangChainEpisodicEmbeddingStore.META_CREATED_AT_EPOCH_MS,
                            Instant.now().toEpochMilli());
            if (symbol != null && !symbol.isBlank()) {
                metadata.put(LangChainEpisodicEmbeddingStore.META_SYMBOL, symbol.trim());
            }
            TextSegment segment = TextSegment.from(summary, metadata);
            embeddingStore.add(Embedding.from(embeddingService.embed(summary)), segment);
        } catch (RuntimeException error) {
            log.warn("完整会话已归档，但情景记忆向量索引失败，historyId={}: {}",
                    history.getId(), error.getMessage());
        }
    }

    /**
     * 按当前问题召回用户隔离的相关会话摘要，向量链路异常时降级为最近归档摘要。
     */
    public List<String> loadRelevantSummaries(Long userId, String question, String symbol) {
        if (!properties.isEnabled()) {
            return loadRecentFallback(userId);
        }
        try {
            Filter filter = new IsEqualTo(LangChainEpisodicEmbeddingStore.META_USER_ID, userId);
            if (symbol != null && !symbol.isBlank()) {
                filter = filter.and(new IsEqualTo(
                        LangChainEpisodicEmbeddingStore.META_SYMBOL, symbol.trim()));
            }
            EmbeddingSearchRequest request = EmbeddingSearchRequest.builder()
                    .queryEmbedding(Embedding.from(embeddingService.embed(question)))
                    .maxResults(Math.max(1, properties.getTopK()))
                    .minScore(Math.max(0, Math.min(1, properties.getMinSimilarity())))
                    .filter(filter)
                    .build();
            EmbeddingSearchResult<TextSegment> result = embeddingStore.search(request);
            if (result.matches().isEmpty()) {
                // 1. 兼容尚未建立摘要向量的旧归档，同时维持升级前的最近摘要能力。
                return loadRecentFallback(userId);
            }
            // 2. 先按相关性选 Top-K，再恢复时间正序，便于上下文按事件先后阅读。
            List<EmbeddingMatch<TextSegment>> matches = new ArrayList<>(result.matches());
            matches.sort(Comparator.comparingLong(this::createdAt));
            return matches.stream()
                    .map(EmbeddingMatch::embedded)
                    .map(TextSegment::text)
                    .filter(text -> text != null && !text.isBlank())
                    .toList();
        } catch (RuntimeException error) {
            log.warn("情景记忆向量检索失败，降级为最近归档摘要，userId={}: {}",
                    userId, error.getMessage());
            return loadRecentFallback(userId);
        }
    }

    private List<String> loadRecentFallback(Long userId) {
        List<ConversationHistory> recent = conversationHistoryService.loadRecent(
                userId, Math.max(1, properties.getRecentFallbackLimit()));
        List<String> summaries = new ArrayList<>();
        for (ConversationHistory history : recent) {
            if (history.getSummary() != null && !history.getSummary().isBlank()) {
                summaries.add(history.getSummary());
            }
        }
        // 1. 数据库按时间倒序返回，Prompt 注入前恢复为时间正序。
        java.util.Collections.reverse(summaries);
        return List.copyOf(summaries);
    }

    private long createdAt(EmbeddingMatch<TextSegment> match) {
        Metadata metadata = match.embedded().metadata();
        if (!metadata.containsKey(LangChainEpisodicEmbeddingStore.META_CREATED_AT_EPOCH_MS)) {
            return Long.MAX_VALUE;
        }
        return metadata.getLong(LangChainEpisodicEmbeddingStore.META_CREATED_AT_EPOCH_MS);
    }
}
