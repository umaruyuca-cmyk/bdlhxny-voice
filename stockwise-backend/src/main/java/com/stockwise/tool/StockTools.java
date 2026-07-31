package com.stockwise.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.dto.FilterResult;
import com.stockwise.entity.KnowledgeChunkWithScore;
import com.stockwise.service.KnowledgeFilter;
import com.stockwise.service.KnowledgeRetrievalService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 对外暴露给推理模型的工具集（function calling）。
 * 每个方法用 @Tool 声明，DeepSeek 据描述自主决定调用哪个、传什么参数；模型不再由 Java 硬编码驱动。
 * 检索类问题用 searchInvestmentKnowledge，标的分析通过 StockAnalysisGateway 走独立 stock-wrapper。
 */
@Slf4j
@Component
public class StockTools {

    private final StockAnalysisGateway stockAnalysisGateway;
    private final KnowledgeRetrievalService retrievalService;
    private final KnowledgeFilter knowledgeFilter;
    private final StockSkillContractValidator contractValidator;
    private final ObjectMapper mapper;

    public StockTools(StockAnalysisGateway stockAnalysisGateway,
                      KnowledgeRetrievalService retrievalService,
                      KnowledgeFilter knowledgeFilter,
                      StockSkillContractValidator contractValidator,
                      ObjectMapper mapper) {
        this.stockAnalysisGateway = stockAnalysisGateway;
        this.retrievalService = retrievalService;
        this.knowledgeFilter = knowledgeFilter;
        this.contractValidator = contractValidator;
        this.mapper = mapper;
    }

    /**
     * 检索投资知识库；用户问术语、策略、政策等知识性问题时由模型自主调用。
     */
    @Tool(description = "检索投资知识库：用户问投资术语、策略、政策、概念等知识性问题时调用。传入用户原始问题，返回最相关的几条知识；无相关知识则返回提示。")
    public String searchInvestmentKnowledge(String question) {
        // 1. 扩大候选集后做相似度、时效、可信度和冲突过滤
        List<KnowledgeChunkWithScore> raw = retrievalService.search(question, 12);
        FilterResult fr = knowledgeFilter.filter(raw);
        if (!fr.retrievalHit() || fr.kept() == null || fr.kept().isEmpty()) {
            return "{\"retrievalHit\":false,\"items\":[],\"message\":\"未检索到达到质量阈值的相关知识。\"}";
        }
        // 2. 返回结构化证据并保留来源、分数、可信度与有效期
        List<Map<String, Object>> items = fr.kept().stream()
                .limit(5)
                .map(this::knowledgeItem)
                .toList();
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("retrievalHit", true);
        result.put("items", items);
        result.put("conflicts", fr.conflicts());
        try {
            return mapper.writeValueAsString(result);
        } catch (Exception e) {
            return "{\"retrievalHit\":false,\"items\":[],\"message\":\"知识检索结果序列化失败。\"}";
        }
    }

    /**
     * 单标的深度分析；用户问某只具体标的时调用。
     */
    @Tool(description = "分析单只标的的技术面。传入6位标的代码（如 600519）和资产类型（stock/etf/open_fund/qdii/auto），返回 MA、RSI、评分、追高信号等技术指标。")
    public String analyzeStock(String code, String assetType) {
        return safe(() -> contractValidator.validateAndAnnotate(
                        stockAnalysisGateway.stock(code, assetType == null ? "auto" : assetType),
                        "stock"),
                "单标的分析失败");
    }

    /**
     * 持仓组合分析；用户问"我的持仓""组合"时调用。
     */
    @Tool(description = "分析用户持仓组合，返回各持仓盈亏、权重、补仓建议、月度资金分配等。无需参数。")
    public String analyzePortfolio() {
        // 1. 无 userId 的自主工具调用不能读取真实持仓，统一交给显式 Route 与 MemoryRouter
        return "{\"success\":false,\"error\":\"PORTFOLIO_CONTEXT_REQUIRED\","
                + "\"message\":\"持仓分析必须通过显式 Route 加载当前用户真实持仓。\"}";
    }

    /**
     * ETF 量化轮动；用户问"轮动/选 ETF/哪几只"时调用。
     */
    @Tool(description = "ETF 量化轮动：传入多个 ETF 代码（空格分隔，如 '510300 159915'）与基准代码，返回动量排名、目标仓位与回测结果。")
    public String analyzeQuant(String codes, String benchmark) {
        return safe(() -> {
            List<String> list = Arrays.asList(codes.split("\\s+"));
            return contractValidator.validateAndAnnotate(
                    stockAnalysisGateway.quant(list, benchmark), "quant");
        }, "量化轮动失败");
    }

    /**
     * 板块排名；用户问"板块/行业/概念"时调用。
     */
    @Tool(description = "获取板块行情排名，返回行业、概念板块的涨跌与资金流向。无需参数。")
    public String listSectors() {
        return safe(() -> contractValidator.validateAndAnnotate(
                stockAnalysisGateway.sector("industry", 20), "sector"), "板块查询失败");
    }

    /**
     * 统一异常兜底：工具失败时返回提示文本，不让异常打断模型的推理循环。
     */
    private String safe(java.util.function.Supplier<String> action, String fallback) {
        try {
            return action.get();
        } catch (Exception e) {
            log.warn("工具调用失败: {}", e.getMessage());
            return fallback + "：" + e.getMessage();
        }
    }

    private Map<String, Object> knowledgeItem(KnowledgeChunkWithScore knowledge) {
        Map<String, Object> item = new LinkedHashMap<>();
        Map<String, Object> metadata = knowledge.getMetadata();
        item.put("content", knowledge.getContent());
        item.put("score", Math.round(knowledge.getScore() * 10_000.0) / 10_000.0);
        item.put("source", metadataValue(metadata, "source"));
        item.put("confidence", metadataValue(metadata, "confidence"));
        item.put("effectiveAt", metadataValue(metadata, "effective_at"));
        item.put("expiresAt", metadataValue(metadata, "expires_at"));
        item.put("version", knowledge.getVersion());
        return item;
    }

    private Object metadataValue(Map<String, Object> metadata, String key) {
        return metadata == null ? null : metadata.get(key);
    }
}
