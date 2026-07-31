package com.stockwise.memory;

import com.stockwise.config.EpisodicMemoryProperties;
import com.stockwise.entity.ConversationEpisodeEmbedding;
import com.stockwise.llm.EmbeddingService;
import com.stockwise.mapper.ConversationEpisodeEmbeddingMapper;
import dev.langchain4j.data.document.Metadata;
import dev.langchain4j.data.embedding.Embedding;
import dev.langchain4j.data.segment.TextSegment;
import dev.langchain4j.store.embedding.EmbeddingMatch;
import dev.langchain4j.store.embedding.EmbeddingSearchRequest;
import dev.langchain4j.store.embedding.EmbeddingSearchResult;
import dev.langchain4j.store.embedding.EmbeddingStore;
import dev.langchain4j.store.embedding.filter.Filter;
import dev.langchain4j.store.embedding.filter.comparison.IsEqualTo;
import dev.langchain4j.store.embedding.filter.logical.And;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 将 LangChain4j 的情景记忆抽象适配到 StockWise 自有 MyBatis/PgVector 表，保留用户隔离和领域评分能力。
 */
@Component
public class LangChainEpisodicEmbeddingStore implements EmbeddingStore<TextSegment> {

    public static final String META_HISTORY_ID = "conversation_history_id";
    public static final String META_USER_ID = "user_id";
    public static final String META_SESSION_ID = "session_id";
    public static final String META_SYMBOL = "symbol";
    public static final String META_CREATED_AT_EPOCH_MS = "created_at_epoch_ms";

    private final ConversationEpisodeEmbeddingMapper mapper;
    private final EmbeddingService embeddingService;
    private final EpisodicMemoryProperties properties;

    public LangChainEpisodicEmbeddingStore(ConversationEpisodeEmbeddingMapper mapper,
                                           EmbeddingService embeddingService,
                                           EpisodicMemoryProperties properties) {
        this.mapper = mapper;
        this.embeddingService = embeddingService;
        this.properties = properties;
    }

    /**
     * 生成索引编号并写入带完整领域元数据的文本片段。
     */
    @Override
    public String add(Embedding embedding, TextSegment embedded) {
        String embeddingId = UUID.randomUUID().toString();
        persist(embeddingId, embedding, embedded);
        return embeddingId;
    }

    /**
     * 仅有向量无法满足用户隔离和归档关联要求，因此拒绝无文本片段写入。
     */
    @Override
    public String add(Embedding embedding) {
        throw new UnsupportedOperationException("情景记忆必须同时提供 TextSegment 与领域元数据");
    }

    /**
     * 仅有索引编号和向量无法恢复摘要内容，因此拒绝不完整写入。
     */
    @Override
    public void add(String id, Embedding embedding) {
        throw new UnsupportedOperationException("情景记忆必须同时提供 TextSegment 与领域元数据");
    }

    /**
     * 把 LangChain4j TextSegment 转成独立的会话摘要向量索引并幂等写入。
     */
    private void persist(String id, Embedding embedding, TextSegment embedded) {
        if (embedded == null) {
            throw new IllegalArgumentException("TextSegment 不能为空");
        }
        Metadata metadata = embedded.metadata();
        ConversationEpisodeEmbedding episode = new ConversationEpisodeEmbedding();
        episode.setEmbeddingId(requireText(id, "embeddingId"));
        episode.setConversationHistoryId(requireLong(metadata, META_HISTORY_ID));
        episode.setUserId(requireLong(metadata, META_USER_ID));
        episode.setSessionId(requireText(metadata.getString(META_SESSION_ID), META_SESSION_ID));
        episode.setSymbol(normalize(metadata.getString(META_SYMBOL)));
        episode.setContent(requireText(embedded.text(), "content"));
        episode.setEmbedding(embedding.vector());
        episode.setMetadata(metadata.toMap());
        int rows = mapper.upsertEpisode(episode);
        if (rows <= 0) {
            throw new IllegalStateException("情景记忆向量索引写入返回0行");
        }
    }

    /**
     * 无文本和领域元数据的批量向量不能安全归属用户，因此拒绝写入。
     */
    @Override
    public List<String> addAll(List<Embedding> embeddings) {
        throw new UnsupportedOperationException("情景记忆批量写入必须提供 TextSegment");
    }

    /**
     * 强制从 Filter 提取 user_id，并将 LangChain4j 查询转换为带时间衰减的领域检索。
     */
    @Override
    public EmbeddingSearchResult<TextSegment> search(EmbeddingSearchRequest request) {
        SearchScope scope = parseScope(request.filter());
        int topK = Math.max(1, request.maxResults());
        int candidateLimit = Math.max(topK, topK * Math.max(1, properties.getCandidateMultiplier()));
        double semanticWeight = boundedWeight(properties.getSemanticWeight());
        double recencyWeight = boundedWeight(properties.getRecencyWeight());
        double weightTotal = semanticWeight + recencyWeight;
        if (weightTotal <= 0) {
            semanticWeight = 1;
            recencyWeight = 0;
            weightTotal = 1;
        }
        // 1. 归一化权重，保证返回给 LangChain4j 的综合分仍位于可解释区间。
        semanticWeight /= weightTotal;
        recencyWeight /= weightTotal;
        List<ConversationEpisodeEmbedding> episodes = mapper.searchRelevant(
                embeddingService.toVectorString(request.queryEmbedding().vector()),
                scope.userId(),
                scope.symbol(),
                topK,
                candidateLimit,
                request.minScore(),
                semanticWeight,
                recencyWeight,
                Math.max(1, properties.getRecencyHalfLifeDays()));
        // 2. 把领域实体恢复为 LangChain4j 的匹配结果，供上层统一消费。
        List<EmbeddingMatch<TextSegment>> matches = new ArrayList<>();
        for (ConversationEpisodeEmbedding episode : episodes) {
            Metadata metadata = new Metadata(episode.getMetadata() == null
                    ? Map.of()
                    : episode.getMetadata());
            metadata.put(META_HISTORY_ID, episode.getConversationHistoryId());
            metadata.put(META_USER_ID, episode.getUserId());
            metadata.put(META_SESSION_ID, episode.getSessionId());
            if (episode.getSymbol() != null) {
                metadata.put(META_SYMBOL, episode.getSymbol());
            }
            if (episode.getCreatedAt() != null) {
                metadata.put(META_CREATED_AT_EPOCH_MS,
                        episode.getCreatedAt().toInstant().toEpochMilli());
            }
            TextSegment segment = TextSegment.from(episode.getContent(), metadata);
            matches.add(new EmbeddingMatch<>(
                    episode.getScore(),
                    episode.getEmbeddingId(),
                    Embedding.from(episode.getEmbedding()),
                    segment));
        }
        return new EmbeddingSearchResult<>(List.copyOf(matches));
    }

    /**
     * 删除指定的可重建向量索引，不影响 conversation_history 原始归档。
     */
    @Override
    public void remove(String id) {
        mapper.deleteByEmbeddingId(id);
    }

    /**
     * 批量删除指定索引；空集合直接返回以避免生成非法 IN 语句。
     */
    @Override
    public void removeAll(Collection<String> ids) {
        if (ids == null || ids.isEmpty()) {
            return;
        }
        mapper.deleteByEmbeddingIds(ids);
    }

    private SearchScope parseScope(Filter filter) {
        SearchScopeBuilder scope = new SearchScopeBuilder();
        collectScope(filter, scope);
        if (scope.userId == null) {
            throw new IllegalArgumentException("情景记忆检索必须提供 user_id 过滤条件");
        }
        return new SearchScope(scope.userId, normalize(scope.symbol));
    }

    private void collectScope(Filter filter, SearchScopeBuilder scope) {
        if (filter == null) {
            return;
        }
        if (filter instanceof And and) {
            collectScope(and.left(), scope);
            collectScope(and.right(), scope);
            return;
        }
        if (filter instanceof IsEqualTo equalTo) {
            if (META_USER_ID.equals(equalTo.key())) {
                scope.userId = toLong(equalTo.comparisonValue(), META_USER_ID);
                return;
            }
            if (META_SYMBOL.equals(equalTo.key())) {
                scope.symbol = String.valueOf(equalTo.comparisonValue());
                return;
            }
        }
        throw new IllegalArgumentException("情景记忆只支持 user_id 与 symbol 的等值过滤");
    }

    private Long requireLong(Metadata metadata, String key) {
        if (!metadata.containsKey(key)) {
            throw new IllegalArgumentException("缺少情景记忆元数据: " + key);
        }
        return toLong(metadata.toMap().get(key), key);
    }

    private Long toLong(Object value, String key) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(value));
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException("情景记忆元数据必须是整数: " + key, error);
        }
    }

    private String requireText(String value, String name) {
        String normalized = normalize(value);
        if (normalized == null) {
            throw new IllegalArgumentException(name + " 不能为空");
        }
        return normalized;
    }

    private String normalize(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim();
    }

    private double boundedWeight(double value) {
        return Math.max(0, Math.min(1, value));
    }

    private record SearchScope(Long userId, String symbol) {
    }

    private static final class SearchScopeBuilder {
        private Long userId;
        private String symbol;
    }
}
