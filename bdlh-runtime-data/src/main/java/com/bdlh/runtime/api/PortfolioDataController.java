package com.bdlh.runtime.api;

import com.bdlh.runtime.dto.AccountSnapshotResponse;
import com.bdlh.runtime.dto.PortfolioPositionsResponse;
import com.bdlh.runtime.dto.TransactionHistoryResponse;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import com.bdlh.runtime.service.JavaDataQueryService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Python LangGraph 调用的持仓、账户和历史交易只读接口。 */
@Tag(name = "Java Data API-组合", description = "向 Python 分析服务提供用户组合只读数据")
@RestController
@RequestMapping("/api/portfolio")
public class PortfolioDataController {

    private final JavaDataAccessGuard accessGuard;
    private final JavaDataQueryService queryService;

    public PortfolioDataController(JavaDataAccessGuard accessGuard, JavaDataQueryService queryService) {
        this.accessGuard = accessGuard;
        this.queryService = queryService;
    }

    @Operation(summary = "查询当前有效持仓")
    @GetMapping("/positions")
    public PortfolioPositionsResponse positions(
            @RequestParam(name = "user_id", required = false) Long requestedUserId) {
        return queryService.positions(accessGuard.resolveUserId(requestedUserId));
    }

    @Operation(summary = "查询账户配置快照")
    @GetMapping("/account")
    public AccountSnapshotResponse account(
            @RequestParam(name = "user_id", required = false) Long requestedUserId) {
        return queryService.account(accessGuard.resolveUserId(requestedUserId));
    }

    @Operation(summary = "查询已发生交易历史")
    @GetMapping("/transactions")
    public TransactionHistoryResponse transactions(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @RequestParam(required = false) Integer limit) {
        return queryService.transactions(accessGuard.resolveUserId(requestedUserId), limit);
    }
}
