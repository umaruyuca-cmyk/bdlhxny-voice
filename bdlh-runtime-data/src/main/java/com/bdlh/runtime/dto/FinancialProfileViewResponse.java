package com.bdlh.runtime.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;
import java.util.List;

/** 用户本人读取金融资料摘要，供设置页预填与乐观锁版本号。 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record FinancialProfileViewResponse(
        long userId,
        long profileVersion,
        String currency,
        BigDecimal cash,
        String riskTolerance,
        BigDecimal maxLossTolerancePct,
        BigDecimal liquidAssets,
        BigDecimal nearTermCashNeeds,
        Integer nearTermCashNeedsHorizonDays,
        String dataMode,
        String confirmationRef,
        List<PositionView> positions) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record PositionView(
            String symbol,
            String name,
            String assetType,
            BigDecimal quantity,
            BigDecimal costPrice,
            String exchange,
            String currency,
            BigDecimal targetWeight) {
    }
}
