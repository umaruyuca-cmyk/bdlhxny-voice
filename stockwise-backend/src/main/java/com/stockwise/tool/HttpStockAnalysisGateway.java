package com.stockwise.tool;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 通过内部 HTTP API 调用独立 stock-wrapper，并解包为现有 Skill JSON 契约。
 */
@Component
public class HttpStockAnalysisGateway implements StockAnalysisGateway {

    private final URI baseUri;
    private final String internalToken;
    private final Duration requestTimeout;
    private final ObjectMapper mapper;
    private final HttpClient httpClient;

    @Autowired
    public HttpStockAnalysisGateway(
            @Value("${stockwise.stock-analysis.base-url:http://localhost:3001}") String baseUrl,
            @Value("${stockwise.stock-analysis.internal-token:}") String internalToken,
            @Value("${stockwise.stock-analysis.connect-timeout-ms:3000}") long connectTimeoutMs,
            @Value("${stockwise.stock-analysis.request-timeout-ms:120000}") long requestTimeoutMs,
            ObjectMapper mapper) {
        this(baseUrl, internalToken, connectTimeoutMs, requestTimeoutMs, mapper, null);
    }

    HttpStockAnalysisGateway(String baseUrl,
                             String internalToken,
                             long connectTimeoutMs,
                             long requestTimeoutMs,
                             ObjectMapper mapper,
                             HttpClient httpClient) {
        this.baseUri = normalizeBaseUri(baseUrl);
        this.internalToken = internalToken == null ? "" : internalToken;
        this.requestTimeout = Duration.ofMillis(requestTimeoutMs);
        this.mapper = mapper;
        this.httpClient = httpClient == null
                ? HttpClient.newBuilder().connectTimeout(Duration.ofMillis(connectTimeoutMs)).build()
                : httpClient;
    }

    /**
     * 调用 Wrapper 单标的分析接口。
     */
    @Override
    public String stock(String code, String assetType) {
        return post("/api/v1/stock/analyze", Map.of(
                "symbol", code,
                "assetType", assetType == null ? "auto" : assetType));
    }

    /**
     * 调用 Wrapper 持仓分析接口。
     */
    @Override
    public String portfolio(PortfolioAnalysisInput input) {
        if (input == null || input.positions().isEmpty()) {
            throw new IllegalArgumentException("组合分析必须提供真实用户持仓");
        }
        return post("/api/v1/portfolio/analyze", mapper.convertValue(input, Map.class));
    }

    /**
     * 调用 Wrapper ETF 量化轮动接口。
     */
    @Override
    public String quant(List<String> codes, String benchmark) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("codes", codes);
        if (benchmark != null && !benchmark.isBlank()) {
            body.put("benchmark", benchmark);
        }
        return post("/api/v1/quant/analyze", body);
    }

    /**
     * 调用 Wrapper 板块排名接口。
     */
    @Override
    public String sector(String type, int limit) {
        String normalizedType = type == null ? "" : type.trim().toLowerCase();
        if (!"industry".equals(normalizedType) && !"concept".equals(normalizedType)) {
            throw new IllegalArgumentException("板块类型只能是 industry 或 concept");
        }
        if (limit < 1 || limit > 100) {
            throw new IllegalArgumentException("板块数量必须在 1 到 100 之间");
        }
        return post("/api/v1/sector/analyze", Map.of(
                "type", normalizedType,
                "limit", limit));
    }

    /**
     * 发送版本化内部请求并返回响应信封中的 Skill data。
     */
    private String post(String path, Map<String, Object> body) {
        String requestId = UUID.randomUUID().toString();
        try {
            HttpRequest.Builder builder = HttpRequest.newBuilder(baseUri.resolve(path))
                    .timeout(requestTimeout)
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .header("X-Request-ID", requestId)
                    .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)));
            if (!internalToken.isBlank()) {
                builder.header("X-Internal-Token", internalToken);
            }

            // 1. Wrapper 执行是有副作用的行情任务，不在客户端自动重试。
            HttpResponse<String> response = httpClient.send(
                    builder.build(),
                    HttpResponse.BodyHandlers.ofString());
            JsonNode root = mapper.readTree(response.body());
            if (response.statusCode() < 200 || response.statusCode() >= 300 || !root.path("success").asBoolean(false)) {
                String message = root.path("error").path("message").asText("stock-wrapper 调用失败");
                String code = root.path("error").path("code").asText("WRAPPER_ERROR");
                throw new IllegalStateException(code + ": " + message);
            }
            JsonNode data = root.path("data");
            if (data.isMissingNode() || data.isNull()) {
                throw new IllegalStateException("stock-wrapper 未返回 Skill 数据");
            }
            return mapper.writeValueAsString(data);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("stock-wrapper 调用被中断，requestId=" + requestId, e);
        } catch (IllegalStateException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("stock-wrapper 调用失败，requestId=" + requestId + ": " + e.getMessage(), e);
        }
    }

    private static URI normalizeBaseUri(String baseUrl) {
        String normalized = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";
        return URI.create(normalized);
    }
}
