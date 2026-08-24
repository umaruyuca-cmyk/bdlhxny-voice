package com.bdlh.runtime.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/** 用户本人完整替换当前持仓事实的请求；派生市值和实际权重不属于该契约。 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record PortfolioPositionsUpdateRequest(
        long expectedProfileVersion,
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
            String riskRole,
            String exchange,
            String currency) {
    }
}
