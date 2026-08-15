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

    /** 账户事实的计价币种；不再由 Data API 硬编码 CNY。 */
    private String currency;

    private BigDecimal cashReserveRatio;

    private String riskTolerance;

    /** 用户明确确认的最大亏损容忍百分数点，范围 0..100。 */
    private BigDecimal maxLossTolerancePct;

    private BigDecimal liquidAssets;

    private BigDecimal nearTermCashNeeds;

    private Integer nearTermCashNeedsHorizonDays;

    /** USER_INPUT / BROKER_SYNC / ACCOUNT_PROVIDER / TEST_FIXTURE。 */
    private String financialDataSource;

    private Long profileVersion;

    private OffsetDateTime confirmedAt;

    private String confirmationRef;

    /** 逗号分隔的行业偏好；Data API 转换为列表后再返回。 */
    private String preferredSectors;

    /** 逗号分隔的禁选标的；Data API 转换为列表后再返回。 */
    private String forbiddenSymbols;

    private Boolean notificationEnabled;

    private Boolean morningBriefEnabled;

    private Boolean closingSummaryEnabled;

    private OffsetDateTime updatedAt;
}
