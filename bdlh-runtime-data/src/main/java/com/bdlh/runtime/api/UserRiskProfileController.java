package com.bdlh.runtime.api;

import com.bdlh.runtime.dto.RiskProfileResponse;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import com.bdlh.runtime.service.JavaDataQueryService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Python LangGraph 调用的用户风险偏好只读接口。 */
@Tag(name = "Java Data API-风险偏好", description = "向 Python 分析服务提供用户风险画像")
@RestController
@RequestMapping("/api/user")
public class UserRiskProfileController {

    private final JavaDataAccessGuard accessGuard;
    private final JavaDataQueryService queryService;

    public UserRiskProfileController(JavaDataAccessGuard accessGuard, JavaDataQueryService queryService) {
        this.accessGuard = accessGuard;
        this.queryService = queryService;
    }

    @Operation(summary = "查询当前用户风险偏好")
    @GetMapping("/risk-profile")
    public RiskProfileResponse riskProfile(
            @RequestParam(name = "user_id", required = false) Long requestedUserId) {
        return queryService.riskProfile(accessGuard.resolveUserId(requestedUserId));
    }
}
