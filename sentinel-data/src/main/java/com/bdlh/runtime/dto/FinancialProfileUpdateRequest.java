package com.bdlh.runtime.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;

/** 用户本人完整替换账户、风险与流动性事实的请求；身份和确认元数据由服务端注入。 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record FinancialProfileUpdateRequest(
        long expectedProfileVersion,
        String currency,
        BigDecimal cash,
        String riskTolerance,
        BigDecimal maxLossTolerancePct,
        BigDecimal liquidAssets,
        BigDecimal nearTermCashNeeds,
        Integer nearTermCashNeedsHorizonDays) {
}
