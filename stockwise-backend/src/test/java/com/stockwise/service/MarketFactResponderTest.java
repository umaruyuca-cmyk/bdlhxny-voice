package com.stockwise.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 验证行情事实模板按问题类型返回确定性字段。
 */
class MarketFactResponderTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final MarketFactResponder responder = new MarketFactResponder(objectMapper);

    @Test
    void indicatorQuestionReturnsTechnicalDataWithoutModelInference() throws Exception {
        JsonNode input = objectMapper.readTree("""
                {
                  "asOf": "2026-07-28T15:00:00+08:00",
                  "data": {
                    "quote": {"price": 100.5},
                    "technical": {"macd": {"state": "golden_cross"}},
                    "score": {"total": 70},
                    "chase": {"level": "none"},
                    "dataQuality": {"allowsDirectionalSignal": true}
                  }
                }
                """);

        JsonNode output = objectMapper.readTree(responder.respond("600519", "600519的MACD是多少", input));

        assertThat(output.path("type").asText()).isEqualTo("MARKET_INDICATOR");
        assertThat(output.path("technical").path("macd").path("state").asText()).isEqualTo("golden_cross");
        assertThat(output.has("history")).isFalse();
    }
}
