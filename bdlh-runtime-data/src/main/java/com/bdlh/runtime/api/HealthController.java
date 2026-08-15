package com.bdlh.runtime.api;

import com.bdlh.runtime.llm.EmbeddingService;
import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;

/**
 * 基础设施连通性探针。
 * 统一探测 PostgreSQL、Redis、Ollama、DeepSeek 四个依赖，便于部署后快速定位哪个组件未就绪。
 */
@RestController
@RequestMapping("/api/v1")
public class HealthController {

    private static final String OLLAMA_API_KEY_HEADER = "x-ollama-api-key";

    private final JdbcTemplate jdbcTemplate;
    private final StringRedisTemplate redisTemplate;
    private final EmbeddingService embeddingService;
    private final RestClient restClient = RestClient.create();

    @Value("${bdlh_runtime.ai.chat-provider:deepseek}")
    private String chatProvider;

    @Value("${spring.ai.ollama.base-url}")
    private String ollamaBaseUrl;

    @Value("${spring.ai.ollama.api-key:}")
    private String ollamaApiKey;

    @Value("${spring.ai.openai.base-url}")
    private String deepseekBaseUrl;

    @Value("${spring.ai.openai.api-key:}")
    private String deepseekApiKey;

    @Value("${spring.ai.openai.chat.options.model}")
    private String deepseekModel;

    @Value("${bdlh_runtime.embedding.provider:dashscope}")
    private String embeddingProvider;

    @Value("${bdlh_runtime.embedding.model:text-embedding-v4}")
    private String embeddingModel;

    public HealthController(JdbcTemplate jdbcTemplate,
                            StringRedisTemplate redisTemplate,
                            EmbeddingService embeddingService) {
        this.jdbcTemplate = jdbcTemplate;
        this.redisTemplate = redisTemplate;
        this.embeddingService = embeddingService;
    }

    /**
     * 返回四组件连通状态，单个组件失败不影响其余探测结果。
     */
    @GetMapping("/ping")
    public Map<String, Object> ping() {
        Map<String, Object> result = new LinkedHashMap<>();
        // 1. 依次探测四个依赖
        result.put("service", "bdlh-runtime-data");
        result.put("postgres", checkPostgres());
        result.put("redis", checkRedis());
        result.put("chatModel", checkChatModel());
        result.put("embedding", checkEmbedding());
        return result;
    }

    /**
     * 根据模型开关返回当前聊天模型的连通或配置状态。
     */
    private Map<String, Object> checkChatModel() {
        // 1. Ollama模式执行真实探测，DeepSeek模式只校验配置以避免消耗Token。
        if ("ollama".equalsIgnoreCase(chatProvider)) {
            return Map.of("provider", "ollama", "detail", checkOllama());
        }
        return Map.of("provider", "deepseek", "detail", checkDeepseek());
    }

    /**
     * 生成一次最小向量以验证当前Embedding服务及返回维数。
     */
    private Map<String, Object> checkEmbedding() {
        try {
            // 1. 使用固定短文本执行真实向量请求。
            float[] vector = embeddingService.embed("BDLH Agent Runtime健康检查");
            return Map.of(
                    "status", "up",
                    "provider", embeddingProvider,
                    "model", embeddingModel,
                    "dimensions", vector.length);
        } catch (Exception error) {
            return Map.of(
                    "status", "down",
                    "provider", embeddingProvider,
                    "model", embeddingModel,
                    "error", safeMsg(error));
        }
    }

    /**
     * 用 SELECT 1 验证数据库连接与权限。
     */
    private Map<String, Object> checkPostgres() {
        try {
            Integer probe = jdbcTemplate.queryForObject("SELECT 1", Integer.class);
            return Map.of("status", "up", "probe", String.valueOf(probe));
        } catch (Exception e) {
            return Map.of("status", "down", "error", safeMsg(e));
        }
    }

    /**
     * 用 Redis PING 命令验证缓存连接。
     */
    private Map<String, Object> checkRedis() {
        try {
            String pong = redisTemplate.getConnectionFactory().getConnection().ping();
            return Map.of("status", "up", "probe", pong);
        } catch (Exception e) {
            return Map.of("status", "down", "error", safeMsg(e));
        }
    }

    /**
     * 调 Ollama 的 /api/tags 验证本地模型服务可达且已加载模型。
     */
    private Map<String, Object> checkOllama() {
        try {
            // 1. 拉取已加载模型列表
            RestClient.RequestHeadersSpec<?> request = restClient.get()
                    .uri(ollamaBaseUrl + "/api/tags");
            // 2. 配置API Key时携带云端网关鉴权头。
            if (StringUtils.hasText(ollamaApiKey)) {
                request.header(OLLAMA_API_KEY_HEADER, ollamaApiKey);
            }
            String body = request.retrieve().body(String.class);
            // 3. 判断是否真的返回了模型（而非空壳服务）
            boolean hasModels = body != null && body.contains("\"models\"");
            return Map.of("status", "up", "hasModels", hasModels);
        } catch (Exception e) {
            return Map.of("status", "down", "error", safeMsg(e));
        }
    }

    /**
     * DeepSeek 不发真实请求（避免消耗 token），仅校验 API Key 是否已配置。
     */
    private Map<String, Object> checkDeepseek() {
        // 1. 判定 Key 是否为非占位符的真实值
        boolean configured = deepseekApiKey != null
                && !deepseekApiKey.isBlank()
                && !deepseekApiKey.startsWith("sk-请");
        return Map.of("status", configured ? "configured" : "missing-key",
                "baseUrl", deepseekBaseUrl,
                "model", deepseekModel,
                "note", "实际调用待阶段 3 验证");
    }

    /**
     * 提取异常消息，避免向调用方暴露完整堆栈。
     */
    private String safeMsg(Exception e) {
        String m = e.getMessage();
        return m == null ? e.getClass().getSimpleName() : m;
    }
}
