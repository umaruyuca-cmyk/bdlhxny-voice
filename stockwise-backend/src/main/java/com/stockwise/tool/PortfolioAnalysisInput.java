package com.stockwise.tool;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * Java 向 stock-wrapper 发送的用户隔离持仓快照，禁止 Wrapper 自行加载示例配置。
 */
public record PortfolioAnalysisInput(
        BigDecimal monthlyBudget,
        BigDecimal cash,
        BigDecimal cashReserveRatio,
        List<Position> positions
) {

    public PortfolioAnalysisInput {
        positions = positions == null ? List.of() : List.copyOf(positions);
    }

    /**
     * 表示组合分析所需的单条真实持仓业务事实。
     */
    public record Position(
            String code,
            String name,
            String assetType,
            BigDecimal avgCost,
            BigDecimal shares,
            LocalDate buyDate,
            BigDecimal targetWeight,
            String sector,
            String riskRole
    ) {
    }
}
