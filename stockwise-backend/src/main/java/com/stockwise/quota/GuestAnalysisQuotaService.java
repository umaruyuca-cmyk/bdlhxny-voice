package com.stockwise.quota;

import com.stockwise.agent.routing.RequestRoute;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.util.EnumSet;
import java.util.List;
import java.util.Set;

/**
 * 使用 Redis 原子限制游客可发起的深度分析次数，避免并发请求绕过上限。
 */
@Service
public class GuestAnalysisQuotaService {

    private static final String KEY_PREFIX = "guest:analysis:";
    private static final Set<RequestRoute> LIMITED_ROUTES = EnumSet.of(
            RequestRoute.STOCK_DECISION,
            RequestRoute.PORTFOLIO_DECISION,
            RequestRoute.QUANT_DECISION,
            RequestRoute.SECTOR_ANALYSIS,
            RequestRoute.MARKET_CAUSAL_ANALYSIS);
    private static final DefaultRedisScript<Long> ACQUIRE_SCRIPT = new DefaultRedisScript<>(
            """
            local current = tonumber(redis.call('GET', KEYS[1]) or '0')
            local limit = tonumber(ARGV[1])
            if current >= limit then
                return 0
            end
            return redis.call('INCR', KEYS[1])
            """,
            Long.class);

    private final StringRedisTemplate redisTemplate;
    private final boolean enabled;
    private final int maxQuestions;

    public GuestAnalysisQuotaService(
            StringRedisTemplate redisTemplate,
            @Value("${stockwise.guest-analysis.enabled:true}") boolean enabled,
            @Value("${stockwise.guest-analysis.max-questions:10}") int maxQuestions) {
        if (maxQuestions <= 0) {
            throw new IllegalArgumentException("stockwise.guest-analysis.max-questions 必须大于0");
        }
        this.redisTemplate = redisTemplate;
        this.enabled = enabled;
        this.maxQuestions = maxQuestions;
    }

    /**
     * 仅对游客深度分析 Route 原子获取一个执行名额，其余请求不触碰计数器。
     */
    public GuestAnalysisQuota acquire(boolean guest, String subjectHash, RequestRoute route) {
        if (!enabled || !guest || !isLimitedRoute(route)) {
            return GuestAnalysisQuota.notApplicable();
        }
        String key = quotaKey(subjectHash);
        try {
            // 1. Lua在Redis单线程内完成上限判断与递增，避免并发GET/INCR超发。
            Long result = redisTemplate.execute(
                    ACQUIRE_SCRIPT,
                    List.of(key),
                    Integer.toString(maxQuestions));
            if (result == null) {
                throw new IllegalStateException("Redis未返回游客分析配额结果");
            }
            if (result == 0L) {
                return new GuestAnalysisQuota(true, false, maxQuestions, maxQuestions, 0);
            }
            int used = Math.toIntExact(result);
            return new GuestAnalysisQuota(true, true, maxQuestions, used, maxQuestions - used);
        } catch (RuntimeException error) {
            throw new GuestAnalysisQuotaUnavailableException("游客分析次数服务暂时不可用", error);
        }
    }

    /**
     * 查询游客当前剩余分析次数，不消耗执行名额。
     */
    public GuestAnalysisQuota status(boolean guest, String subjectHash) {
        if (!enabled || !guest) {
            return GuestAnalysisQuota.notApplicable();
        }
        String key = quotaKey(subjectHash);
        try {
            String value = redisTemplate.opsForValue().get(key);
            int used = value == null ? 0 : Math.max(0, Integer.parseInt(value));
            int boundedUsed = Math.min(used, maxQuestions);
            return new GuestAnalysisQuota(
                    true,
                    boundedUsed < maxQuestions,
                    maxQuestions,
                    boundedUsed,
                    maxQuestions - boundedUsed);
        } catch (RuntimeException error) {
            throw new GuestAnalysisQuotaUnavailableException("游客分析次数服务暂时不可用", error);
        }
    }

    /**
     * 判断 Route 是否属于会消耗游客分析次数的深度分析路径。
     */
    public boolean isLimitedRoute(RequestRoute route) {
        return route != null && LIMITED_ROUTES.contains(route);
    }

    private String quotaKey(String subjectHash) {
        if (subjectHash == null || !subjectHash.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("游客主体哈希格式无效");
        }
        return KEY_PREFIX + subjectHash;
    }
}
