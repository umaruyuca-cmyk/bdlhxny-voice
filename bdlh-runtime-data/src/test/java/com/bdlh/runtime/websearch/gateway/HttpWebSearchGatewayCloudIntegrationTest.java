package com.bdlh.runtime.websearch.gateway;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.bdlh.runtime.websearch.model.SearchPurpose;
import com.bdlh.runtime.websearch.model.SearchTask;
import com.bdlh.runtime.websearch.model.WebSearchResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 使用显式开关验证本地Java Gateway到云端Wrapper的真实链路，默认测试不会读取外部凭证。
 */
class HttpWebSearchGatewayCloudIntegrationTest {

    @Test
    @EnabledIfEnvironmentVariable(named = "WEB_SEARCH_LIVE_TEST", matches = "true")
    void callsCloudWrapperWithFixedContract() {
        HttpWebSearchGateway gateway = new HttpWebSearchGateway(
                required("WEB_SEARCH_ENDPOINT_URL"),
                required("WEB_SEARCH_AGENT_ID"),
                required("WEB_SEARCH_AGENT_TOKEN"),
                5_000,
                30_000,
                new ObjectMapper().findAndRegisterModules());
        SearchTask task = new SearchTask(
                "java-cloud-test",
                SearchPurpose.NEWS_CATALYST,
                "600519 贵州茅台 最新公告",
                "600519",
                30,
                List.of(),
                5);

        WebSearchResponse response = gateway.search(List.of(task));

        assertThat(response.provider()).isEqualTo("searxng");
        assertThat(response.errors()).isEmpty();
        assertThat(response.results()).isNotEmpty().hasSizeLessThanOrEqualTo(5);
        assertThat(response.results())
                .allSatisfy(result -> {
                    assertThat(result.taskId()).isEqualTo("java-cloud-test");
                    assertThat(result.resultId()).isNotBlank();
                    assertThat(result.purpose()).isEqualTo(SearchPurpose.NEWS_CATALYST);
                    assertThat(result.title()).isNotBlank();
                    assertThat(result.url()).startsWith("http");
                    assertThat(result.domain()).isNotBlank();
                    assertThat(result.snippet()).isNotNull();
                    assertThat(result.sourceType()).isIn("WEB", "OFFICIAL");
                    assertThat(result.provider()).isEqualTo("searxng");
                    assertThat(result.retrievedAt()).isNotNull();
                    assertThat(result.relevanceScore()).isNotNull().isGreaterThanOrEqualTo(0);
                });
    }

    private String required(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " 未配置");
        }
        return value;
    }
}
