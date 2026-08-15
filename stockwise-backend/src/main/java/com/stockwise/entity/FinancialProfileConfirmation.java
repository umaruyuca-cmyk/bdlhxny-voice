package com.stockwise.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 用户金融资料确认审计。只保存版本、字段路径和请求指纹，不保存完整金融载荷。
 */
@Data
@TableName("public.financial_profile_confirmations")
public class FinancialProfileConfirmation {

    @TableId
    private String confirmationRef;

    private Long userId;

    private Long profileVersion;

    private String actionType;

    private String idempotencyKey;

    private String requestFingerprint;

    private String changedFields;

    private OffsetDateTime confirmedAt;
}
