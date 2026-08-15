package com.bdlh.runtime.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 从已校验的 stock 命令结果提取行情事实，避免为价格和K线调用付费模型。
 */
@Component
public class MarketFactResponder {

    private final ObjectMapper objectMapper;

    public MarketFactResponder(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    /**
     * 根据问题返回固定行情 JSON，K线和技术指标请求只附加对应的确定性字段。
     */
    public String respond(String symbol, String question, JsonNode validatedRoot) {
        JsonNode data = validatedRoot.path("data");
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("type", responseType(question));
        response.put("symbol", symbol);
        response.put("asOf", validatedRoot.path("asOf").asText(data.path("dataQuality").path("asOf").asText("")));
        response.put("quote", objectMapper.convertValue(data.path("quote"), Object.class));
        response.put("dataQuality", objectMapper.convertValue(data.path("dataQuality"), Object.class));
        if (isKline(question)) {
            response.put("history", objectMapper.convertValue(data.path("history"), Object.class));
        }
        if (isIndicator(question)) {
            response.put("technical", objectMapper.convertValue(data.path("technical"), Object.class));
            response.put("score", objectMapper.convertValue(data.path("score"), Object.class));
            response.put("chase", objectMapper.convertValue(data.path("chase"), Object.class));
        }
        try {
            return objectMapper.writeValueAsString(response);
        } catch (Exception e) {
            throw new IllegalStateException("行情事实序列化失败", e);
        }
    }

    private boolean isKline(String question) {
        return question != null && (question.contains("K线") || question.contains("k线")
                || question.matches(".*日\\s*K.*"));
    }

    private boolean isIndicator(String question) {
        return question != null && question.matches(
                "(?is).*(MA5|MA10|MA20|MA60|MACD|RSI|KDJ|均线|成交量|量比|技术指标).*");
    }

    private String responseType(String question) {
        if (isKline(question)) {
            return "MARKET_KLINE";
        }
        return isIndicator(question) ? "MARKET_INDICATOR" : "MARKET_QUOTE";
    }
}
