package com.stockwise.llm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.ollama.OllamaEmbeddingModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;

import java.util.Map;

/**
 * 可切换的向量生成服务，默认调用DashScope text-embedding-v4并保留Ollama回退能力。
 * 临时向量（检索）与正式向量（入库）都走这里，二者区别仅在调用时机与是否落库，本服务不关心用途。
 */
@Service
public class EmbeddingService {

    private final OllamaEmbeddingModel ollamaEmbeddingModel;
    private final ObjectMapper objectMapper;
    private final RestClient dashscopeClient;
    private final String provider;
    private final String apiKey;
    private final String model;
    private final int dimensions;

    public EmbeddingService(
            OllamaEmbeddingModel ollamaEmbeddingModel,
            ObjectMapper objectMapper,
            @Value("${stockwise.embedding.provider:dashscope}") String provider,
            @Value("${stockwise.embedding.base-url:https://dashscope.aliyuncs.com/compatible-mode/v1}")
            String baseUrl,
            @Value("${stockwise.embedding.api-key:}") String apiKey,
            @Value("${stockwise.embedding.model:text-embedding-v4}") String model,
            @Value("${stockwise.embedding.dimensions:1024}") int dimensions) {
        this.ollamaEmbeddingModel = ollamaEmbeddingModel;
        this.objectMapper = objectMapper;
        this.provider = provider == null ? "dashscope" : provider.trim().toLowerCase();
        this.apiKey = apiKey == null ? "" : apiKey.trim();
        this.model = model;
        this.dimensions = dimensions;
        this.dashscopeClient = RestClient.builder()
                .baseUrl(trimTrailingSlash(baseUrl))
                .build();
    }

    /**
     * 把文本转向量，供检索或入库使用。
     */
    public float[] embed(String text) {
        // 1. 仅显式选择ollama时使用旧模型，其余情况走text-embedding-v4。
        if ("ollama".equals(provider)) {
            return ollamaEmbeddingModel.embed(text);
        }
        return embedWithDashScope(text);
    }

    /**
     * 把 float[] 转成 pgvector 文本 "[v1,v2,...]"，作为检索/去重 SQL 的入参。
     */
    public String toVectorString(float[] vec) {
        // 1. 按 pgvector 文本格式拼接
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vec.length; i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append(vec[i]);
        }
        sb.append(']');
        return sb.toString();
    }

    /**
     * 调用OpenAI兼容的DashScope Embeddings接口并解析浮点向量。
     */
    private float[] embedWithDashScope(String text) {
        if (!StringUtils.hasText(apiKey)) {
            throw new IllegalStateException("stockwise.embedding.api-key未配置");
        }
        try {
            // 1. 使用官方OpenAI兼容协议请求固定1024维向量。
            String response = dashscopeClient.post()
                    .uri("/embeddings")
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey)
                    .body(Map.of(
                            "model", model,
                            "input", text,
                            "dimensions", dimensions,
                            "encoding_format", "float"))
                    .retrieve()
                    .body(String.class);
            // 2. 解析data[0].embedding并校验维数，防止写入错误维度的pgvector列。
            JsonNode embedding = objectMapper.readTree(response)
                    .path("data")
                    .path(0)
                    .path("embedding");
            if (!embedding.isArray() || embedding.size() != dimensions) {
                throw new IllegalStateException(
                        "向量服务返回维数异常，expected=" + dimensions + ", actual=" + embedding.size());
            }
            float[] vector = new float[dimensions];
            for (int i = 0; i < dimensions; i++) {
                vector[i] = (float) embedding.get(i).asDouble();
            }
            return vector;
        } catch (IllegalStateException error) {
            throw error;
        } catch (Exception error) {
            throw new IllegalStateException("text-embedding-v4调用失败: " + error.getMessage(), error);
        }
    }

    /**
     * 去掉Base URL末尾斜杠，避免请求路径出现双斜杠。
     */
    private static String trimTrailingSlash(String baseUrl) {
        if (!StringUtils.hasText(baseUrl)) {
            throw new IllegalArgumentException("stockwise.embedding.base-url不能为空");
        }
        String normalized = baseUrl.trim();
        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }
}
