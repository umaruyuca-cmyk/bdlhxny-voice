package com.stockwise.websearch.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import com.stockwise.websearch.model.SearchPurpose;
import com.stockwise.websearch.model.SearchTask;
import com.stockwise.websearch.model.WebSearchResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

/**
 * 验证 Java 只发送通用 Wrapper 协议且不会发送 symbol。
 */
class HttpWebSearchGatewayTest {

    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void mapsDomainTaskToGenericTransportContract() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/api/search", exchange -> {
            JsonNode request = mapper.readTree(exchange.getRequestBody());
            assertFalse(request.path("tasks").get(0).has("symbol"));
            byte[] response = """
                    {
                      "schemaVersion":"1.0",
                      "requestId":"request-1",
                      "provider":"fake",
                      "results":[{
                        "resultId":"result-1",
                        "taskId":"task-1",
                        "purposeCode":"POLICY_UPDATE",
                        "title":"政策",
                        "url":"https://gov.cn/policy",
                        "domain":"gov.cn",
                        "snippet":"摘要",
                        "sourceType":"OFFICIAL",
                        "provider":"fake",
                        "publishedAt":null,
                        "retrievedAt":"2026-07-28T00:00:00Z",
                        "relevanceScore":1.0
                      }],
                      "errors":[]
                    }
                    """.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        URI endpoint = URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/api/search");
        HttpWebSearchGateway gateway = new HttpWebSearchGateway(
                endpoint, "stockwise", "a".repeat(32), Duration.ofSeconds(3), HttpClient.newHttpClient(), mapper);

        WebSearchResponse response = gateway.search(List.of(new SearchTask(
                "task-1", SearchPurpose.POLICY_UPDATE, "最新证券政策",
                "600519", 30, List.of("gov.cn"), 5)));

        assertEquals(1, response.results().size());
        assertEquals(SearchPurpose.POLICY_UPDATE, response.results().get(0).purpose());
    }
}
