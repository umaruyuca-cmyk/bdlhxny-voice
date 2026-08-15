package com.bdlh.runtime.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;

/** 当前用户账户配置快照；不包含券商账户和交易执行能力。 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record AccountSnapshotResponse(
        DataAccessMetadata metadata,
        String currency,
        BigDecimal cash,
        BigDecimal monthlyBudget,
        BigDecimal cashReserveRatio,
        BigDecimal liquidAssets,
        BigDecimal nearTermCashNeeds,
        Integer nearTermCashNeedsHorizonDays,
        Long profileVersion) {
}
