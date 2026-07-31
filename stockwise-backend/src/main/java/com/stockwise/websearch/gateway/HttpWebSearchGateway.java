package com.stockwise.websearch.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.websearch.model.SearchError;
import com.stockwise.websearch.model.SearchPurpose;
import com.stockwise.websearch.model.SearchResult;
import com.stockwise.websearch.model.SearchTask;
import com.stockwise.websearch.model.WebSearchResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 通过版本化 HTTP 协议调用共享 web-search-wrapper，并隔离 SearXNG 原始结构。
 */
@Component
public class HttpWebSearchGateway implements WebSearchGateway {

    private final URI endpoint;
    private final String agentId;
    private final String agentToken;
    private final Duration requestTimeout;
    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;

    @Autowired
    public HttpWebSearchGateway(
            @Value("${stockwise.web-search.endpoint-url:http://localhost:3002/api/search}") String endpointUrl,
            @Value("${stockwise.web-search.agent-id:stockwise}") String agentId,
            @Value("${stockwise.web-search.agent-token:}") String agentToken,
            @Value("${stockwise.web-search.connect-timeout-ms:3000}") long connectTimeoutMs,
            @Value("${stockwise.web-search.request-timeout-ms:15000}") long requestTimeoutMs,
            ObjectMapper objectMapper) {
        this(URI.create(endpointUrl),
                agentId,
                agentToken,
                Duration.ofMillis(requestTimeoutMs),
                HttpClient.newBuilder().connectTimeout(Duration.ofMillis(connectTimeoutMs)).build(),
                objectMapper);
    }

    HttpWebSearchGateway(URI endpoint,
                         String agentId,
                         String agentToken,
                         Duration requestTimeout,
                         HttpClient httpClient,
                         ObjectMapper objectMapper) {
        this.endpoint = endpoint;
        this.agentId = agentId;
        this.agentToken = agentToken;
        this.requestTimeout = requestTimeout;
        this.httpClient = httpClient;
        this.objectMapper = objectMapper;
    }

    /**
     * 将领域任务转换为通用协议并返回固定 SearchResult。
     */
    @Override
    public WebSearchResponse search(List<SearchTask> tasks) {
        if (agentToken == null || agentToken.length() < 32) {
            throw new IllegalStateException("WEB_SEARCH_AGENT_TOKEN 未配置或少于32位");
        }
        String requestId = UUID.randomUUID().toString();
        try {
            HttpRequest request = HttpRequest.newBuilder(endpoint)
                    .timeout(requestTimeout)
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .header("X-Agent-Id", agentId)
                    .header("X-Search-Token", agentToken)
                    .header("X-Request-Id", requestId)
                    .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(payload(tasks))))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new IllegalStateException("共享搜索服务返回 HTTP " + response.statusCode());
            }
            return parse(response.body(), tasks);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("共享搜索服务调用被中断", e);
        } catch (Exception e) {
            if (e instanceof IllegalStateException stateException) {
                throw stateException;
            }
            throw new IllegalStateException("共享搜索服务调用失败", e);
        }
    }

    private Map<String, Object> payload(List<SearchTask> tasks) {
        List<Map<String, Object>> transportTasks = tasks.stream().map(task -> {
            Map<String, Object> value = new LinkedHashMap<>();
            value.put("taskId", task.taskId());
            value.put("purposeCode", task.purpose().name());
            value.put("mode", task.purpose() == SearchPurpose.NEWS_CATALYST
                    || task.purpose() == SearchPurpose.MARKET_ATTENTION ? "NEWS" : "GENERAL");
            value.put("query", task.query());
            value.put("language", "zh-CN");
            value.put("freshnessDays", task.freshnessDays());
            value.put("includeDomains", task.preferredDomains());
            value.put("excludeDomains", List.of());
            value.put("maxResults", task.maxResults());
            return value;
        }).toList();
        return Map.of("schemaVersion", "1.0", "tasks", transportTasks);
    }

    private WebSearchResponse parse(String body, List<SearchTask> tasks) throws Exception {
        JsonNode root = objectMapper.readTree(body);
        if (!"1.0".equals(root.path("schemaVersion").asText())) {
            throw new IllegalStateException("共享搜索响应版本不兼容");
        }
        Map<String, SearchPurpose> purposeByTask = new HashMap<>();
        tasks.forEach(task -> purposeByTask.put(task.taskId(), task.purpose()));
        List<SearchResult> results = new ArrayList<>();
        for (JsonNode item : root.path("results")) {
            String taskId = item.path("taskId").asText();
            SearchPurpose purpose = purposeByTask.get(taskId);
            if (purpose == null) {
                continue;
            }
            results.add(new SearchResult(
                    item.path("resultId").asText(),
                    taskId,
                    purpose,
                    item.path("title").asText(),
                    item.path("url").asText(),
                    item.path("domain").asText(),
                    item.path("snippet").asText(),
                    item.path("sourceType").asText("WEB"),
                    item.path("provider").asText(root.path("provider").asText()),
                    instant(item.get("publishedAt")),
                    instant(item.get("retrievedAt")),
                    item.path("relevanceScore").asDouble(0)));
        }
        List<SearchError> errors = new ArrayList<>();
        for (JsonNode item : root.path("errors")) {
            errors.add(new SearchError(
                    item.path("taskId").asText(),
                    item.path("code").asText(),
                    item.path("message").asText()));
        }
        return new WebSearchResponse(root.path("requestId").asText(),
                root.path("provider").asText(), results, errors);
    }

    private Instant instant(JsonNode value) {
        if (value == null || value.isNull() || value.asText().isBlank()) {
            return null;
        }
        try {
            return Instant.parse(value.asText());
        } catch (Exception e) {
            return null;
        }
    }

}
