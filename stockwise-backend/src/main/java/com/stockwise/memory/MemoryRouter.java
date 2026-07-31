package com.stockwise.memory;

import com.stockwise.dto.IngestResult;
import com.stockwise.service.EpisodicMemoryService;
import com.stockwise.service.KnowledgeIngestService;
import com.stockwise.service.UserFeedbackService;
import com.stockwise.service.UserPortfolioService;
import com.stockwise.skill.KnowledgeCandidate;
import com.stockwise.tool.PortfolioAnalysisInput;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 作为工作、情景、语义和业务记忆的统一入口，避免业务组件把数据写入错误存储。
 */
@Component
public class MemoryRouter {

    private final SessionStateService sessionStateService;
    private final EpisodicMemoryService episodicMemoryService;
    private final KnowledgeIngestService knowledgeIngestService;
    private final UserFeedbackService userFeedbackService;
    private final UserPortfolioService userPortfolioService;

    public MemoryRouter(SessionStateService sessionStateService,
                        EpisodicMemoryService episodicMemoryService,
                        KnowledgeIngestService knowledgeIngestService,
                        UserFeedbackService userFeedbackService,
                        UserPortfolioService userPortfolioService) {
        this.sessionStateService = sessionStateService;
        this.episodicMemoryService = episodicMemoryService;
        this.knowledgeIngestService = knowledgeIngestService;
        this.userFeedbackService = userFeedbackService;
        this.userPortfolioService = userPortfolioService;
    }

    /**
     * 返回载荷的固定存储目标，用于审计、测试和新增记忆类型时的穷举校验。
     */
    public MemoryDestination destination(MemoryPayloadType type) {
        return switch (type) {
            case SESSION_STATE -> MemoryDestination.WORKING_REDIS;
            case CONVERSATION_ARCHIVE, AGENT_RUN, USER_FEEDBACK ->
                    MemoryDestination.EPISODIC_POSTGRES;
            case CONFIRMED_KNOWLEDGE -> MemoryDestination.SEMANTIC_PGVECTOR;
            case PORTFOLIO_POSITION, USER_FINANCIAL_CONFIG ->
                    MemoryDestination.BUSINESS_POSTGRES;
        };
    }

    /**
     * 从 Redis 加载当前工作记忆。
     */
    public SessionState loadWorking(String sessionId) {
        return sessionStateService.load(sessionId);
    }

    /**
     * 通过版本 CAS 保存当前工作记忆。
     */
    public long saveWorking(SessionState state) {
        return sessionStateService.save(state);
    }

    /**
     * 通过版本 CAS 清除已经归档的工作记忆。
     */
    public void clearWorking(SessionState state) {
        sessionStateService.clear(state);
    }

    /**
     * 加载用户最近的会话情景摘要。
     */
    public List<String> loadRelevantEpisodes(Long userId, String question, String symbol) {
        return episodicMemoryService.loadRelevantSummaries(userId, question, symbol);
    }

    /**
     * 将完整会话归档为情景记忆。
     */
    public void archiveEpisode(Long userId,
                               String sessionId,
                               String symbol,
                               List<ConversationMessage> messages,
                               String summary) {
        episodicMemoryService.archive(userId, sessionId, symbol, messages, summary);
    }

    /**
     * 把用户确认的候选知识写入 PgVector 语义记忆。
     */
    public IngestResult ingestConfirmedKnowledge(KnowledgeCandidate candidate,
                                                 String problem,
                                                 Long userId) {
        return knowledgeIngestService.ingest(candidate, problem, userId);
    }

    /**
     * 保存结构化用户反馈并关联最近一次 Agent Run。
     */
    public void recordFeedback(Long userId,
                               String sessionId,
                               UUID runId,
                               FeedbackType type,
                               String message,
                               Map<String, Object> metadata) {
        userFeedbackService.record(userId, sessionId, runId, type, message, metadata);
    }

    /**
     * 加载用户隔离的真实持仓与资金配置。
     */
    public PortfolioAnalysisInput loadRequiredPortfolio(Long userId) {
        return userPortfolioService.loadRequired(userId);
    }
}
