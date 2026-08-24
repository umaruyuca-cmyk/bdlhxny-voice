package com.bdlh.runtime.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;
import java.util.List;

/** 用户风险偏好的只读快照。 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record RiskProfileResponse(
        DataAccessMetadata metadata,
        String riskTolerance,
        BigDecimal maxLossTolerancePct,
        BigDecimal cashReserveRatio,
        List<String> preferredSectors,
        List<String> forbiddenSymbols,
        Long profileVersion) {
}
