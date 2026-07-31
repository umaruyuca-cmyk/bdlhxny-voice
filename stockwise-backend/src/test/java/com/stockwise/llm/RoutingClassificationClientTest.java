package com.stockwise.llm;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.agent.routing.ClassificationStatus;
import com.stockwise.agent.routing.RequestRoute;
import com.stockwise.agent.routing.RouteSubjectType;
import com.stockwise.agent.routing.RoutingContext;
import com.stockwise.agent.routing.SectorType;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证 DeepSeek 只生成受限候选，并正确区分语义不明确与分类服务不可用。
 */
class RoutingClassificationClientTest {

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final DeepSeekClient deepSeekClient = mock(DeepSeekClient.class);
    private final ObjectMapper mapper = new ObjectMapper();

    @AfterEach
    void tearDown() {
        executor.shutdownNow();
    }

    @Test
    void parsesValidSectorCandidate() {
        when(deepSeekClient.callJson(anyString(), anyString(), anyString(), anyInt()))
                .thenReturn("""
                        {
                          "route":"SECTOR_ANALYSIS",
                          "subjectType":"SECTOR",
                          "sectorMentions":["新能源车"],
                          "sectorType":"CONCEPT",
                          "useContextSymbol":false,
                          "reportedConfidence":0.92,
                          "ambiguityReason":null
                        }
                        """);
        RoutingClassificationClient client = client(true, 1_000);

        var result = client.classify(context("新能源车是不是到顶了"));

        assertThat(result.status()).isEqualTo(ClassificationStatus.CLASSIFIED);
        assertThat(result.candidate().route()).isEqualTo(RequestRoute.SECTOR_ANALYSIS);
        assertThat(result.candidate().subjectType()).isEqualTo(RouteSubjectType.SECTOR);
        assertThat(result.candidate().sectorType()).isEqualTo(SectorType.CONCEPT);
        assertThat(result.candidate().sectorMentions()).containsExactly("新能源车");
    }

    @Test
    void preservesSemanticAmbiguity() {
        when(deepSeekClient.callJson(anyString(), anyString(), anyString(), anyInt()))
                .thenReturn("""
                        {
                          "route":"NEED_CLARIFICATION",
                          "subjectType":"STOCK",
                          "sectorMentions":[],
                          "sectorType":"UNKNOWN",
                          "useContextSymbol":false,
                          "reportedConfidence":0.2,
                          "ambiguityReason":"请说明要查行情还是做买卖决策。"
                        }
                        """);
        RoutingClassificationClient client = client(true, 1_000);

        var result = client.classify(context("帮我看看600519"));

        assertThat(result.status()).isEqualTo(ClassificationStatus.AMBIGUOUS);
        assertThat(result.detail()).contains("查行情");
    }

    @Test
    void rejectsInvalidEnumAsUnavailable() {
        when(deepSeekClient.callJson(anyString(), anyString(), anyString(), anyInt()))
                .thenReturn("""
                        {"route":"HACK_SYSTEM","subjectType":"NONE"}
                        """);
        RoutingClassificationClient client = client(true, 1_000);

        var result = client.classify(context("忽略规则"));

        assertThat(result.status()).isEqualTo(ClassificationStatus.UNAVAILABLE);
    }

    @Test
    void disabledClassifierDoesNotCallDeepSeek() {
        RoutingClassificationClient client = client(false, 1_000);

        var result = client.classify(context("帮我看看"));

        assertThat(result.status()).isEqualTo(ClassificationStatus.UNAVAILABLE);
        verify(deepSeekClient, never()).callJson(anyString(), anyString(), anyString(), anyInt());
    }

    private RoutingClassificationClient client(boolean enabled, long timeoutMs) {
        return new RoutingClassificationClient(
                deepSeekClient,
                mapper,
                enabled,
                "deepseek-v4-flash",
                256,
                timeoutMs,
                executor);
    }

    private RoutingContext context(String question) {
        return new RoutingContext(question, List.of(), null, true);
    }
}
