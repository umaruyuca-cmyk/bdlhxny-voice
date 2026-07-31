package com.stockwise.websearch.policy;

import com.stockwise.websearch.model.SearchTask;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 在外部调用前校验任务数量、隐私字段和查询预算，避免完整用户上下文泄露。
 */
@Component
public class SearchPolicyValidator {

    private static final int MAX_TASKS = 3;
    private static final int MAX_RESULTS = 5;
    private static final Pattern SYMBOL_PATTERN = Pattern.compile("^\\d{6}$");
    private static final Pattern DOMAIN_PATTERN = Pattern.compile("^(?:[a-z0-9-]+\\.)+[a-z]{2,}$",
            Pattern.CASE_INSENSITIVE);
    private static final List<String> PRIVATE_MARKERS = List.of(
            "用户id", "用户 id", "手机号", "身份证", "我的成本", "持仓成本", "我的预算", "账户余额");

    /**
     * 返回不可变的已校验任务，非法任务直接拒绝且不调用 Wrapper。
     */
    public List<SearchTask> validate(List<SearchTask> tasks) {
        if (tasks == null || tasks.isEmpty() || tasks.size() > MAX_TASKS) {
            throw new IllegalArgumentException("搜索任务数量必须在1到3之间");
        }
        Set<String> taskIds = new HashSet<>();
        return tasks.stream().map(task -> validateOne(task, taskIds)).toList();
    }

    private SearchTask validateOne(SearchTask task, Set<String> taskIds) {
        if (task == null || task.taskId() == null || task.taskId().isBlank() || !taskIds.add(task.taskId())) {
            throw new IllegalArgumentException("搜索任务ID不能为空或重复");
        }
        if (task.purpose() == null) {
            throw new IllegalArgumentException("搜索用途不能为空");
        }
        String query = task.query() == null ? "" : task.query().trim();
        if (query.length() < 2 || query.length() > 200) {
            throw new IllegalArgumentException("搜索词长度必须在2到200之间");
        }
        String lowerQuery = query.toLowerCase(Locale.ROOT);
        if (PRIVATE_MARKERS.stream().anyMatch(lowerQuery::contains)) {
            throw new IllegalArgumentException("搜索词包含禁止发送的用户私有字段");
        }
        if (task.symbol() != null && !task.symbol().isBlank() && !SYMBOL_PATTERN.matcher(task.symbol()).matches()) {
            throw new IllegalArgumentException("标的代码必须是6位数字");
        }
        int maxResults = task.maxResults() == null ? MAX_RESULTS : task.maxResults();
        if (maxResults < 1 || maxResults > MAX_RESULTS) {
            throw new IllegalArgumentException("每个任务最多保留5条结果");
        }
        List<String> domains = task.preferredDomains().stream()
                .map(domain -> domain.trim().toLowerCase(Locale.ROOT))
                .peek(domain -> {
                    if (!DOMAIN_PATTERN.matcher(domain).matches()) {
                        throw new IllegalArgumentException("搜索域名格式无效: " + domain);
                    }
                })
                .distinct()
                .limit(10)
                .toList();
        return new SearchTask(task.taskId(), task.purpose(), query, task.symbol(),
                normalizeFreshness(task.freshnessDays()), domains, maxResults);
    }

    private Integer normalizeFreshness(Integer days) {
        if (days == null) {
            return null;
        }
        if (days < 1 || days > 3650) {
            throw new IllegalArgumentException("搜索时间范围必须在1到3650天之间");
        }
        return days;
    }
}
