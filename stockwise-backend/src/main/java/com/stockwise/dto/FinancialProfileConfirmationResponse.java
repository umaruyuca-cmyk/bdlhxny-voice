package com.stockwise.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.time.OffsetDateTime;

/** 服务端生成的金融资料确认结果，不回显完整敏感金融载荷。 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record FinancialProfileConfirmationResponse(
        long userId,
        long profileVersion,
        String dataMode,
        String confirmationRef,
        OffsetDateTime confirmedAt) {
}
