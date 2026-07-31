package com.stockwise.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 用户资金与通知配置实体，组合分析只消费其中的确定性资金字段。
 */
@Data
@TableName("public.user_configs")
public class UserConfig {

    @TableId
    private Long userId;

    private Integer monthlyBudget;

    private BigDecimal cash;

    private BigDecimal cashReserveRatio;

    private Boolean notificationEnabled;

    private Boolean morningBriefEnabled;

    private Boolean closingSummaryEnabled;

    private OffsetDateTime updatedAt;
}
