package com.stockwise.api;

import com.stockwise.dto.FinancialProfileConfirmationResponse;
import com.stockwise.dto.FinancialProfileUpdateRequest;
import com.stockwise.dto.PortfolioPositionsUpdateRequest;
import com.stockwise.security.SingleUserContext;
import com.stockwise.service.FinancialProfileCommandService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 用户本人维护金融资料的认证设置入口。
 *
 * <p>本 Controller 不属于 Java Data API，也不会注册为 Agent Capability。</p>
 */
@Tag(name = "用户设置-金融资料", description = "用户本人录入并确认自己的金融事实")
@RestController
@RequestMapping("/api/v1/user")
public class FinancialProfileSettingsController {

    private final SingleUserContext userContext;
    private final FinancialProfileCommandService commandService;

    public FinancialProfileSettingsController(
            SingleUserContext userContext,
            FinancialProfileCommandService commandService) {
        this.userContext = userContext;
        this.commandService = commandService;
    }

    @Operation(summary = "完整替换并确认账户、风险和流动性资料")
    @PutMapping("/financial-profile")
    public FinancialProfileConfirmationResponse replaceFinancialProfile(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody FinancialProfileUpdateRequest request) {
        long userId = userContext.requireAuthenticatedUserId();
        return commandService.replaceFinancialProfile(userId, idempotencyKey, request);
    }

    @Operation(summary = "完整替换并确认当前持仓；未提交的旧持仓会停用")
    @PutMapping("/portfolio-positions")
    public FinancialProfileConfirmationResponse replacePositions(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody PortfolioPositionsUpdateRequest request) {
        long userId = userContext.requireAuthenticatedUserId();
        return commandService.replacePositions(userId, idempotencyKey, request);
    }
}
