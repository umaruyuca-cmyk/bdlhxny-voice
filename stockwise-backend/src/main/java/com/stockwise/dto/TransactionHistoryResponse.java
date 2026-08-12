package com.stockwise.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/** 已发生交易的只读历史；本契约不提供下单、撤单或修改入口。 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record TransactionHistoryResponse(
        DataAccessMetadata metadata,
        List<Transaction> transactions) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Transaction(
            Long transactionId,
            String symbol,
            String name,
            String transactionType,
            BigDecimal quantity,
            BigDecimal price,
            BigDecimal amount,
            String currency,
            LocalDate tradeDate,
            String note) {
    }
}
