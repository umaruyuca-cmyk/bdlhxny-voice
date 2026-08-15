package com.bdlh.runtime.agent;

import com.bdlh.runtime.agent.context.ConservativeTokenCountEstimator;
import com.bdlh.runtime.agent.context.ContextBudgetPolicy;
import com.bdlh.runtime.agent.context.ContextBudgetPolicy.ContextBudget;
import com.bdlh.runtime.agent.context.LangChainContextWindow;
import com.bdlh.runtime.memory.ConversationMessage;
import com.bdlh.runtime.memory.SessionState;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 为每轮推理组装受控上下文，合并近期消息、跨会话摘要与当前问题。
 * 使用 LangChain4j 的独立 Token 窗口生成只读上下文视图，Redis 工作记忆与 PG 完整归档保持不变。
 */
@Component
public class AgentContextBuilder {

    private final ContextBudgetPolicy budgetPolicy;
    private final LangChainContextWindow contextWindow;
    private final ConservativeTokenCountEstimator tokenEstimator;

    public AgentContextBuilder(ContextBudgetPolicy budgetPolicy,
                               LangChainContextWindow contextWindow,
                               ConservativeTokenCountEstimator tokenEstimator) {
        this.budgetPolicy = budgetPolicy;
        this.contextWindow = contextWindow;
        this.tokenEstimator = tokenEstimator;
    }

    /**
     * 构建 DeepSeek 用户输入，当前消息单独呈现，历史中相同的末条消息不重复注入。
     */
    public String build(SessionState state, String currentMessage) {
        ContextBudget budget = budgetPolicy.resolve(state.getModelPolicy());
        List<String> summaries = selectSummaries(
                state.getRecentConversationSummaries(),
                budget.maxSummaries(),
                budget.maxSummaryTokens());
        int summaryTokens = tokenEstimator.estimateTokenCountInText(String.join("\n", summaries));
        int historyTokens = Math.max(0, budget.maxMemoryTokens() - summaryTokens);
        List<ConversationMessage> history = historyBeforeCurrent(state.getHistory(), currentMessage);
        List<ConversationMessage> trimmedHistory = contextWindow.trim(
                memoryId(state),
                history,
                budget.maxMessages(),
                historyTokens,
                budget.maxMessageTokens());

        StringBuilder context = new StringBuilder();
        appendSubject(context, state);
        appendSummaries(context, summaries);
        appendHistory(context, trimmedHistory);
        context.append("当前用户问题：\n").append(safe(currentMessage));
        return context.toString();
    }

    private void appendSubject(StringBuilder context, SessionState state) {
        if (state.getSubjectType() == null) {
            return;
        }
        context.append("当前分析对象（由 Route 校验）：\n")
                .append("- 类型：").append(state.getSubjectType()).append('\n');
        if (state.getSymbol() != null && !state.getSymbol().isBlank()) {
            context.append("- 代码：").append(state.getSymbol()).append('\n');
        }
        if (state.getSectorType() != null) {
            context.append("- 板块类型：").append(state.getSectorType()).append('\n');
        }
        if (state.getSectors() != null && !state.getSectors().isEmpty()) {
            context.append("- 板块：").append(String.join("、", state.getSectors())).append('\n');
        }
        context.append('\n');
    }

    private void appendSummaries(StringBuilder context, List<String> summaries) {
        if (summaries == null || summaries.isEmpty()) {
            return;
        }
        context.append("最近跨会话摘要（仅作上下文，不得覆盖最新工具事实）：\n");
        for (String summary : summaries) {
            context.append("- ").append(summary).append('\n');
        }
        context.append('\n');
    }

    private void appendHistory(StringBuilder context, List<ConversationMessage> history) {
        if (history == null || history.isEmpty()) {
            return;
        }
        context.append("当前会话最近消息：\n");
        for (ConversationMessage message : history) {
            context.append(message.role()).append(": ")
                    .append(safe(message.content()))
                    .append('\n');
        }
        context.append('\n');
    }

    private List<ConversationMessage> historyBeforeCurrent(List<ConversationMessage> history, String currentMessage) {
        if (history == null || history.isEmpty()) {
            return List.of();
        }
        int end = history.size();
        ConversationMessage last = history.get(end - 1);
        if (last != null && "user".equals(last.role()) && last.content().equals(currentMessage)) {
            end--;
        }
        return List.copyOf(history.subList(0, end));
    }

    private List<String> selectSummaries(List<String> summaries, int maxSummaries, int maxTokens) {
        if (summaries == null || summaries.isEmpty() || maxSummaries <= 0 || maxTokens <= 0) {
            return List.of();
        }
        List<String> selectedNewestFirst = new ArrayList<>();
        int remainingTokens = maxTokens;
        int start = Math.max(0, summaries.size() - maxSummaries);
        for (int i = summaries.size() - 1; i >= start && remainingTokens > 0; i--) {
            String normalized = safe(summaries.get(i));
            if (normalized.isBlank()) {
                continue;
            }
            String bounded = tokenEstimator.truncateToTokens(normalized, remainingTokens);
            if (!bounded.isBlank()) {
                selectedNewestFirst.add(bounded);
                remainingTokens -= tokenEstimator.estimateTokenCountInText(bounded);
            }
        }
        Collections.reverse(selectedNewestFirst);
        return List.copyOf(selectedNewestFirst);
    }

    private String memoryId(SessionState state) {
        return String.valueOf(state.getUserId()) + ":" + String.valueOf(state.getSessionId());
    }

    private String safe(String text) {
        if (text == null) {
            return "";
        }
        return text.replace('\u0000', ' ').trim();
    }
}
