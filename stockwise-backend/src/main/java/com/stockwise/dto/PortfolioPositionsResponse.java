package com.stockwise.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/** 当前用户持仓的脱敏只读响应。 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PortfolioPositionsResponse(
        DataAccessMetadata metadata,
        List<Position> positions) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Position(
            String symbol,
            String name,
            String assetType,
            BigDecimal quantity,
            BigDecimal costPrice,
            LocalDate buyDate,
            BigDecimal targetWeight,
            String sector,
            String riskRole) {
    }
}
