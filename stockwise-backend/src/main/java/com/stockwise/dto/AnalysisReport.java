package com.stockwise.dto;

import java.math.BigDecimal;
import java.util.List;

/**
 * 前端可直接渲染的完整分析报告，对应 stock-agent.html 的报告面板。
 * 确定性字段（quote/levels/indicators/score）由后端从 stock-analysis-skill 的 JSON 映射；
 * 解释性字段（summary/note/reasons 文本）由 DeepSeek 生成。
 */
public record AnalysisReport(
        String traceId,
        int version,
        String symbol,
        String name,
        String shortName,
        String asOf,
        String timezone,
        Quote quote,
        Decision decision,
        List<Reason> reasons,
        Levels levels,
        Indicators indicators,
        DataQuality dataQuality,
        List<BigDecimal> klines,
        List<BigDecimal> ma20line
) {
    /** 经行情接口核验的价格快照。 */
    public record Quote(BigDecimal price, BigDecimal change, BigDecimal changePercent) {
    }

    /** 代码指标与模型解释共同形成的决策结果。 */
    public record Decision(String action, String note, String chaseRisk, String chaseNote,
                           int techScore, String techStage, String summary) {
    }

    /** 支持当前结论的一条主要原因。 */
    public record Reason(String title, String text) {
    }

    /** 报告使用的关键交易价位。 */
    public record Levels(BigDecimal strengthen, BigDecimal confirm, BigDecimal repair,
                         BigDecimal current, BigDecimal risk) {
    }

    /** 后端代码计算的核心技术指标。 */
    public record Indicators(Indicator trend, Indicator macd, Indicator rsi6,
                             Indicator volumeRatio, Indicator ma20Bias) {
    }

    /** 单个技术指标的展示值与解释。 */
    public record Indicator(Object value, String note) {
    }

    /** 数据时效状态，驱动前端时效徽章（实时/延时/休市）。 */
    public record DataQuality(String status, String label) {
    }
}
