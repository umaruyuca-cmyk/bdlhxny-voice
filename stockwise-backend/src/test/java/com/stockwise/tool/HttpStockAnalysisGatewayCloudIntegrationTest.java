package com.stockwise.tool;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 按显式开关验证Java到云端stock-wrapper再到私有Skill的真实链路。
 */
class HttpStockAnalysisGatewayCloudIntegrationTest {

    @Test
    void shouldCallDeployedStockSkillWithTraceableContract() throws Exception {
        String enabled = System.getenv("RUN_STOCK_WRAPPER_CLOUD_TEST");
        String baseUrl = System.getenv("STOCK_WRAPPER_URL");
        String token = System.getenv("STOCK_WRAPPER_TOKEN");
        Assumptions.assumeTrue("true".equalsIgnoreCase(enabled),
                "设置RUN_STOCK_WRAPPER_CLOUD_TEST=true后执行云端Skill测试");
        Assumptions.assumeTrue(baseUrl != null && !baseUrl.isBlank(),
                "缺少STOCK_WRAPPER_URL");
        Assumptions.assumeTrue(token != null && !token.isBlank(),
                "缺少STOCK_WRAPPER_TOKEN");

        ObjectMapper mapper = new ObjectMapper();
        HttpStockAnalysisGateway gateway = new HttpStockAnalysisGateway(
                baseUrl, token, 5_000L, 120_000L, mapper, null);

        JsonNode result = mapper.readTree(gateway.stock("600519", "stock"));

        assertThat(result.path("schemaVersion").asText()).isEqualTo("1.1");
        assertThat(result.path("command").asText()).isEqualTo("stock");
        assertThat(result.path("methodology").path("id").asText())
                .isEqualTo("stockwise-objective-analysis");
        assertThat(result.path("methodology").path("version").asText()).isNotBlank();
        assertThat(result.path("decisionBasis").isObject()).isTrue();
        assertThat(result.path("dataQuality").isObject()).isTrue();
        assertThat(result.path("asOf").asText()).isNotBlank();
    }
}
