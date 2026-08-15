package com.bdlh.runtime.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 用户持仓实体，对应 portfolio_positions 表，覆盖股票/ETF/场外基金/QDII 四类资产。
 */
@Data
@TableName("public.portfolio_positions")
public class PortfolioPosition {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String code;

    private String name;

    private String assetType;

    private BigDecimal avgCost;

    private BigDecimal shares;

    private LocalDate buyDate;

    private BigDecimal targetWeight;

    private String sector;

    private String riskRole;

    /** 交易所/市场标识；旧数据未知时保持 null，不根据证券代码猜测。 */
    private String exchange;

    /** 持仓计价币种；旧数据未知时保持 null。 */
    private String currency;

    /** USER_INPUT / BROKER_SYNC / ACCOUNT_PROVIDER / TEST_FIXTURE。 */
    private String dataSource;

    private OffsetDateTime confirmedAt;

    /** 受控确认或同步引用，不是客户端提供的任意字符串。 */
    private String sourceRef;

    private Boolean active;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}
