package com.stockwise.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 已发生交易的历史记录。该实体只通过查询服务读取，不提供交易执行能力。
 */
@Data
@TableName("public.portfolio_transactions")
public class PortfolioTransaction {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String symbol;

    private String name;

    private String transactionType;

    private BigDecimal quantity;

    private BigDecimal price;

    private BigDecimal amount;

    private String currency;

    private LocalDate tradeDate;

    private String note;

    private OffsetDateTime createdAt;
}
