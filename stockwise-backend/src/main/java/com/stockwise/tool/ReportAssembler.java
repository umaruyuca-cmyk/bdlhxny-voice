package com.stockwise.tool;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.dto.AnalysisReport;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * 把 stock-analysis-skill 的 stock --json 输出组装成前端可渲染的 AnalysisReport。
 * 确定性数据（quote/score/indicators/levels/dataQuality/klines）在此映射；
 * 解释性文本（summary/note/reasons/techStage）留空，由调用方用 DeepSeek 后补。
 */
@Component
public class ReportAssembler {

    private final ObjectMapper mapper;
    private final StockSkillContractValidator contractValidator;

    public ReportAssembler(ObjectMapper mapper, StockSkillContractValidator contractValidator) {
        this.mapper = mapper;
        this.contractValidator = contractValidator;
    }

    /**
     * 解析 skill JSON 并映射为 AnalysisReport；解析失败抛运行时异常。
     */
    public AnalysisReport assemble(String skillJson) {
        try {
            JsonNode root = contractValidator.validate(skillJson, "stock");
            JsonNode data = root.path("data");
            JsonNode quote = data.path("quote");
            JsonNode score = data.path("score");
            JsonNode technical = data.path("technical");
            JsonNode chase = data.path("chase");
            JsonNode dq = data.path("dataQuality");
            JsonNode history = data.path("history");

            String symbol = data.path("code").asText();
            String name = data.path("name").asText();

            // 1. 走势图数据：history 的 close 价数组
            List<BigDecimal> klines = new ArrayList<>();
            for (JsonNode bar : history) {
                BigDecimal close = decimalOrNull(bar.path("close"));
                if (close != null) {
                    klines.add(close);
                }
            }

            // 2. 关键价位：MA 系列 + 风险位（low20 或 ma60 的 97%）
            BigDecimal price = decimalOrNull(quote.path("price"));
            BigDecimal ma5 = decimalOrNull(technical.path("ma").path("ma5"));
            BigDecimal ma10 = decimalOrNull(technical.path("ma").path("ma10"));
            BigDecimal ma20 = decimalOrNull(technical.path("ma").path("ma20"));
            BigDecimal low20 = decimalOrNull(technical.path("support").path("low20"));
            BigDecimal riskBase = low20 != null
                    ? low20
                    : decimalOrNull(technical.path("ma").path("ma60"));
            BigDecimal risk = riskBase != null ? riskBase.multiply(new BigDecimal("0.97")) : null;
            StockSkillContractValidator.StockConsumerPolicy consumerPolicy =
                    contractValidator.policy(root);
            String action = mapAction(score.path("signal").asText());
            // 3. 时效不允许方向信号时强制观望；追高硬警告只阻断买入类动作
            if (!consumerPolicy.directionalSignalAllowed()
                    || ("买入".equals(action) && !consumerPolicy.buyOrAddAllowed())) {
                action = "观望";
            }

            // 4. 组装报告（解释性字段留空，由 DeepSeek 补）
            return new AnalysisReport(
                    null, 1, symbol, name, name,
                    root.path("asOf").asText(dq.path("asOf").asText()),
                    "Asia/Shanghai",
                    new AnalysisReport.Quote(
                            price,
                            decimalOrNull(quote.path("changeAmount")),
                            decimalOrNull(quote.path("changePct"))),
                    new AnalysisReport.Decision(
                            action,
                            "",
                            chase.path("label").asText(),
                            "",
                            score.path("total").asInt(),
                            "",
                            ""),
                    List.of(),
                    new AnalysisReport.Levels(ma5, ma10, ma20, price, risk),
                    new AnalysisReport.Indicators(
                            new AnalysisReport.Indicator(technical.path("alignment").asText(), ""),
                            new AnalysisReport.Indicator(technical.path("macd").path("state").asText(""), ""),
                            new AnalysisReport.Indicator(technical.path("rsi").path("rsi6").asDouble(), technical.path("rsi").path("zone").asText()),
                            new AnalysisReport.Indicator(technical.path("volume").path("volumeRatio").asDouble(), ""),
                            new AnalysisReport.Indicator(technical.path("deviation").path("ma20").asDouble() + "%", "")),
                    new AnalysisReport.DataQuality(dq.path("status").asText(), dq.path("label").asText()),
                    klines,
                    null
            );
        } catch (Exception e) {
            throw new RuntimeException("组装 AnalysisReport 失败: " + e.getMessage(), e);
        }
    }

    /**
     * 把 skill 的评分信号映射成中文动作；未知信号默认观望。
     */
    private String mapAction(String signal) {
        if (signal == null) {
            return "观望";
        }
        return switch (signal) {
            case "strong_buy", "buy" -> "买入";
            case "hold" -> "持有";
            case "wait" -> "观望";
            case "sell", "strong_sell" -> "卖出";
            default -> "观望";
        };
    }

    private BigDecimal decimalOrNull(JsonNode node) {
        if (node == null || !node.isNumber()) {
            return null;
        }
        return node.decimalValue();
    }
}
