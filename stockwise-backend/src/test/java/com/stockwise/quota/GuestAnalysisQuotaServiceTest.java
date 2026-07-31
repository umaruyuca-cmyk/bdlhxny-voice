package com.stockwise.quota;

import com.stockwise.agent.routing.RequestRoute;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证游客次数仅约束深度分析Route，并使用Redis原子结果计算剩余额度。
 */
class GuestAnalysisQuotaServiceTest {

    private static final String SUBJECT_HASH = "a".repeat(64);

    @Test
    void shouldNotConsumeQuotaForMarketFact() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        GuestAnalysisQuotaService service = new GuestAnalysisQuotaService(redisTemplate, true, 10);

        GuestAnalysisQuota quota = service.acquire(true, SUBJECT_HASH, RequestRoute.MARKET_FACT);

        assertThat(quota.applicable()).isFalse();
        verify(redisTemplate, never()).execute(any(), anyList(), any());
    }

    @Test
    void shouldReturnRemainingQuotaFromAtomicAcquire() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        when(redisTemplate.execute(any(), anyList(), eq("10"))).thenReturn(4L);
        GuestAnalysisQuotaService service = new GuestAnalysisQuotaService(redisTemplate, true, 10);

        GuestAnalysisQuota quota = service.acquire(
                true,
                SUBJECT_HASH,
                RequestRoute.STOCK_DECISION);

        assertThat(quota.applicable()).isTrue();
        assertThat(quota.allowed()).isTrue();
        assertThat(quota.used()).isEqualTo(4);
        assertThat(quota.remaining()).isEqualTo(6);
    }

    @Test
    void shouldRejectWhenAtomicAcquireReturnsZero() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        when(redisTemplate.execute(any(), anyList(), eq("10"))).thenReturn(0L);
        GuestAnalysisQuotaService service = new GuestAnalysisQuotaService(redisTemplate, true, 10);

        GuestAnalysisQuota quota = service.acquire(
                true,
                SUBJECT_HASH,
                RequestRoute.MARKET_CAUSAL_ANALYSIS);

        assertThat(quota.allowed()).isFalse();
        assertThat(quota.used()).isEqualTo(10);
        assertThat(quota.remaining()).isZero();
    }

    @SuppressWarnings("unchecked")
    @Test
    void shouldReadCurrentStatusWithoutConsuming() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ValueOperations<String, String> valueOperations = mock(ValueOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.get("guest:analysis:" + SUBJECT_HASH)).thenReturn("7");
        GuestAnalysisQuotaService service = new GuestAnalysisQuotaService(redisTemplate, true, 10);

        GuestAnalysisQuota quota = service.status(true, SUBJECT_HASH);

        assertThat(quota.used()).isEqualTo(7);
        assertThat(quota.remaining()).isEqualTo(3);
        verify(redisTemplate, never()).execute(any(), anyList(), any());
    }
}
