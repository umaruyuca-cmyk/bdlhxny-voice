package com.stockwise.llm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.agent.routing.ClassificationResult;
import com.stockwise.agent.routing.RequestRoute;
import com.stockwise.agent.routing.RouteCandidate;
import com.stockwise.agent.routing.RouteSource;
import com.stockwise.agent.routing.RouteSubjectType;
import com.stockwise.agent.routing.RoutingContext;
import com.stockwise.agent.routing.SectorType;
import com.stockwise.agent.routing.SemanticRouteClassifier;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * 使用固定 Prompt 和 JSON Output 调用 DeepSeek 生成候选路由，不提供工具或最终执行权限。
 */
@Slf4j
@Service
public class RoutingClassificationClient implements SemanticRouteClassifier {

    private static final String SYSTEM_PROMPT = """
            你是 StockWise 的路由候选分类器，只判断语义，不回答问题、不提供投资建议、不授权工具。
            只输出一个 JSON 对象，禁止输出其他文字。

            route 只能是：
            GENERAL_CHAT, KNOWLEDGE_QA, EXTERNAL_RESEARCH, MARKET_FACT,
            SECTOR_FACT, SECTOR_ATTENTION, STOCK_DECISION, PORTFOLIO_DECISION, QUANT_DECISION,
            SECTOR_ANALYSIS, MARKET_CAUSAL_ANALYSIS, NEED_CLARIFICATION。

            subjectType 只能是：
            NONE, STOCK, ETF_POOL, SECTOR, PORTFOLIO, MARKET。

            安全规则：
            1. 禁止生成、补全或猜测股票代码。
            2. sectorMentions 只能摘录用户问题中出现的行业、板块或概念名称。
            3. sectorType 只能是 INDUSTRY、CONCEPT、UNKNOWN。
            4. 只有用户使用“这只、它、当前标的”等指代时，useContextSymbol 才能为 true。
            5. QUANT_DECISION 表示至少两个ETF或基金的比较、轮动和目标权重。
            6. SECTOR_FACT 表示板块涨跌、热度、排名、资金流、换手和已经计算出的趋势事实，不做买卖判断。
            7. SECTOR_ATTENTION 表示互联网讨论度、搜索关注、舆情热度或大众关注代理。
            8. SECTOR_ANALYSIS 只表示板块未来、买卖、追高、仓位或方向性投资判断。
            9. MARKET_CAUSAL_ANALYSIS 表示外部事件对股票、板块或市场的影响。
            10. 最新政策、公告、新闻和公开事实查询属于 EXTERNAL_RESEARCH。
            11. 意图、主体或必要参数不清晰时返回 NEED_CLARIFICATION，并填写 ambiguityReason。
            12. reportedConfidence 取值为 0 到 1，只是自评，系统会再次校验。

            JSON 格式：
            {
              "route": "SECTOR_ANALYSIS",
              "subjectType": "SECTOR",
              "sectorMentions": ["新能源车"],
              "sectorType": "CONCEPT",
              "useContextSymbol": false,
              "reportedConfidence": 0.92,
              "ambiguityReason": null
            }
            """;

    private final DeepSeekClient deepSeekClient;
    private final ObjectMapper mapper;
    private final boolean enabled;
    private final String model;
    private final int maxTokens;
    private final long timeoutMs;
    private final ExecutorService executor;

    public RoutingClassificationClient(
            DeepSeekClient deepSeekClient,
            ObjectMapper mapper,
            @Value("${stockwise.routing.semantic.enabled:false}") boolean enabled,
            @Value("${stockwise.routing.semantic.model:deepseek-v4-flash}") String model,
            @Value("${stockwise.routing.semantic.max-output-tokens:256}") int maxTokens,
            @Value("${stockwise.routing.semantic.total-timeout-ms:2500}") long timeoutMs,
            @Qualifier("routingClassifierExecutor") ExecutorService executor) {
        this.deepSeekClient = deepSeekClient;
        this.mapper = mapper;
        this.enabled = enabled;
        this.model = model;
        this.maxTokens = Math.max(64, Math.min(maxTokens, 512));
        this.timeoutMs = Math.max(250L, timeoutMs);
        this.executor = executor;
    }

    /**
     * 发送最小化上下文并把模型输出解析为仍需 Java 校验的 RouteCandidate。
     */
    @Override
    public ClassificationResult classify(RoutingContext context) {
        if (!enabled) {
            return ClassificationResult.unavailable("ROUTING_CLASSIFIER_DISABLED");
        }
        try {
            // 1. 只发送问题、已抽取代码和能力标志，不发送代码以外的账户数据。
            Map<String, Object> input = new LinkedHashMap<>();
            input.put("question", context.question());
            input.put("explicitSymbols", context.explicitSymbols());
            input.put("contextSymbolAvailable", context.contextSymbol() != null);
            input.put("portfolioAvailable", context.portfolioAvailable());
            String userMessage = mapper.writeValueAsString(input);
            String raw = callWithinDeadline(userMessage);
            if (raw == null || raw.isBlank()) {
                return ClassificationResult.unavailable("ROUTING_CLASSIFIER_EMPTY");
            }

            // 2. JSON Output 仍需执行枚举和字段范围校验。
            JsonNode node = mapper.readTree(raw);
            RequestRoute route = enumValue(RequestRoute.class, node.path("route").asText(""));
            RouteSubjectType subjectType = enumValue(
                    RouteSubjectType.class, node.path("subjectType").asText("NONE"));
            if (route == null || subjectType == null) {
                return ClassificationResult.unavailable("ROUTING_CLASSIFIER_INVALID_ENUM");
            }
            String ambiguityReason = nullableText(node.path("ambiguityReason"));
            if (route == RequestRoute.NEED_CLARIFICATION) {
                return ClassificationResult.ambiguous(
                        ambiguityReason == null ? "请补充你想分析的具体目标。" : ambiguityReason);
            }
            RouteCandidate candidate = new RouteCandidate(
                    route,
                    subjectType,
                    textArray(node.path("sectorMentions")),
                    SectorType.from(node.path("sectorType").asText("")),
                    node.path("useContextSymbol").asBoolean(false),
                    clamp(node.path("reportedConfidence").asDouble(0.0)),
                    ambiguityReason,
                    RouteSource.DEEPSEEK);
            return ClassificationResult.classified(candidate);
        } catch (Exception error) {
            log.warn("DeepSeek 路由候选分类失败: {}", error.getMessage());
            return ClassificationResult.unavailable("ROUTING_CLASSIFIER_FAILED");
        }
    }

    private String callWithinDeadline(String userMessage)
            throws InterruptedException, ExecutionException, TimeoutException {
        Future<String> future;
        try {
            future = executor.submit(() -> deepSeekClient.callJson(
                    SYSTEM_PROMPT,
                    userMessage,
                    model,
                    maxTokens));
        } catch (RejectedExecutionException error) {
            throw new IllegalStateException("ROUTING_CLASSIFIER_BUSY", error);
        }
        try {
            return future.get(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (TimeoutException error) {
            future.cancel(true);
            throw error;
        } catch (InterruptedException error) {
            future.cancel(true);
            Thread.currentThread().interrupt();
            throw error;
        }
    }

    private List<String> textArray(JsonNode node) {
        if (!node.isArray()) {
            return List.of();
        }
        List<String> values = new ArrayList<>();
        node.forEach(item -> {
            String value = item.asText("").trim();
            if (!value.isBlank() && value.length() <= 24) {
                values.add(value);
            }
        });
        return List.copyOf(values);
    }

    private String nullableText(JsonNode node) {
        if (node == null || node.isNull() || node.isMissingNode()) {
            return null;
        }
        String value = node.asText("").trim();
        return value.isBlank() ? null : value;
    }

    private double clamp(double value) {
        return Math.max(0.0, Math.min(1.0, value));
    }

    private <E extends Enum<E>> E enumValue(Class<E> type, String value) {
        try {
            return Enum.valueOf(type, value.trim().toUpperCase());
        } catch (Exception error) {
            return null;
        }
    }
}
