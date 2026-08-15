package com.bdlh.runtime.tool;

import java.util.List;

/**
 * 隔离 Agent 业务与 stock-analysis-skill 的具体调用协议，便于独立部署和替换传输实现。
 */
public interface StockAnalysisGateway {

    /**
     * 获取单标的结构化分析结果。
     */
    String stock(String code, String assetType);

    /**
     * 使用当前用户的真实持仓快照获取组合分析结果。
     */
    String portfolio(PortfolioAnalysisInput input);

    /**
     * 获取 ETF 多标的量化轮动结果。
     */
    String quant(List<String> codes, String benchmark);

    /**
     * 获取受限类型和数量的板块排名结果。
     */
    String sector(String type, int limit);

    /**
     * 兼容旧调用点获取默认行业排名，新代码应显式传入类型和数量。
     */
    default String sector() {
        return sector("industry", 20);
    }
}
