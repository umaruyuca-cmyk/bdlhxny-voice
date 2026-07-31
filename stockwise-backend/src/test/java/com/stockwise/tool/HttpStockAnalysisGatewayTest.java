package com.stockwise.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.List;
import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证 Java Gateway 与 stock-wrapper 版本化 HTTP 契约的解包和错误处理。
 */
class HttpStockAnalysisGatewayTest {

    private HttpServer server;

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void shouldUnwrapSkillContractFromWrapperEnvelope() throws Exception {
        startServer(exchange -> respond(exchange, 200, """
                {
                  "success": true,
                  "requestId": "request-1",
                  "contractVersion": "1.0",
                  "data": {
                    "schemaVersion": "1.1",
                    "command": "stock",
                    "asOf": "2026-07-28T10:00:00+08:00",
                    "data": {}
                  },
                  "error": null
                }
                """));
        HttpStockAnalysisGateway gateway = gateway();

        String result = gateway.stock("588200", "etf");

        assertTrue(result.contains("\"schemaVersion\":\"1.1\""));
        assertTrue(result.contains("\"command\":\"stock\""));
    }

    @Test
    void shouldExposeWrapperErrorWithoutAutomaticRetry() throws Exception {
        startServer(exchange -> respond(exchange, 429, """
                {
                  "success": false,
                  "requestId": "request-2",
                  "contractVersion": "1.0",
                  "data": null,
                  "error": {
                    "code": "WRAPPER_BUSY",
                    "message": "分析服务繁忙"
                  }
                }
                """));
        HttpStockAnalysisGateway gateway = gateway();

        IllegalStateException error = assertThrows(
                IllegalStateException.class,
                () -> gateway.sector());

        assertEquals("WRAPPER_BUSY: 分析服务繁忙", error.getMessage());
    }

    @Test
    void shouldSendRealPortfolioSnapshotToWrapper() throws Exception {
        startServer(exchange -> {
            String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            assertTrue(requestBody.contains("\"monthlyBudget\":5000"));
            assertTrue(requestBody.contains("\"code\":\"588200\""));
            assertTrue(!requestBody.contains("databaseId"));
            respond(exchange, 200, """
                    {
                      "success": true,
                      "requestId": "request-3",
                      "contractVersion": "1.0",
                      "data": {
                        "schemaVersion": "1.1",
                        "command": "portfolio",
                        "data": {}
                      },
                      "error": null
                    }
                    """);
        });
        PortfolioAnalysisInput input = new PortfolioAnalysisInput(
                new BigDecimal("5000"),
                new BigDecimal("12000"),
                new BigDecimal("0.20"),
                List.of(new PortfolioAnalysisInput.Position(
                        "588200",
                        "科创芯片ETF",
                        "etf",
                        new BigDecimal("1.20"),
                        new BigDecimal("1000"),
                        LocalDate.of(2026, 1, 2),
                        new BigDecimal("0.30"),
                        "半导体",
                        "进攻")));

        String result = gateway().portfolio(input);

        assertTrue(result.contains("\"command\":\"portfolio\""));
    }

    @Test
    void shouldSendBoundedSectorTypeAndLimit() throws Exception {
        startServer(exchange -> {
            String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            assertTrue(requestBody.contains("\"type\":\"concept\""));
            assertTrue(requestBody.contains("\"limit\":100"));
            respond(exchange, 200, """
                    {
                      "success": true,
                      "requestId": "request-sector",
                      "contractVersion": "1.0",
                      "data": {
                        "schemaVersion": "1.1",
                        "command": "sector",
                        "data": {}
                      },
                      "error": null
                    }
                    """);
        });

        String result = gateway().sector("concept", 100);

        assertTrue(result.contains("\"command\":\"sector\""));
    }

    @Test
    void shouldRejectUnsupportedSectorArgumentsBeforeHttpCall() throws Exception {
        startServer(exchange -> respond(exchange, 500, "{}"));
        HttpStockAnalysisGateway gateway = gateway();

        assertThrows(IllegalArgumentException.class, () -> gateway.sector("all", 20));
        assertThrows(IllegalArgumentException.class, () -> gateway.sector("industry", 101));
    }

    private HttpStockAnalysisGateway gateway() {
        return new HttpStockAnalysisGateway(
                "http://127.0.0.1:" + server.getAddress().getPort(),
                "test-token",
                1_000,
                5_000,
                new ObjectMapper().findAndRegisterModules(),
                null);
    }

    private void startServer(ExchangeHandler handler) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            try {
                assertEquals("test-token", exchange.getRequestHeaders().getFirst("X-Internal-Token"));
                handler.handle(exchange);
            } finally {
                exchange.close();
            }
        });
        server.start();
    }

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
    }

    @FunctionalInterface
    private interface ExchangeHandler {
        void handle(HttpExchange exchange) throws IOException;
    }
}
