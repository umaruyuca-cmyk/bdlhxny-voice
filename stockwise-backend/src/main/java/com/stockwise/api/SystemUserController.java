package com.stockwise.api;

import com.stockwise.dto.SystemUserView;
import com.stockwise.service.SystemUserService;
import com.stockwise.security.SingleUserContext;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 系统用户管理查询接口，为本地 Swagger 联调提供真实的 MySQL 业务链路。
 */
@Tag(name = "系统管理-用户", description = "MySQL 用户数据查询接口")
@RestController
@RequestMapping("/api/v1/system/users")
public class SystemUserController {

    private final SystemUserService systemUserService;
    private final SingleUserContext singleUserContext;

    public SystemUserController(SystemUserService systemUserService, SingleUserContext singleUserContext) {
        this.systemUserService = systemUserService;
        this.singleUserContext = singleUserContext;
    }

    /**
     * 分页前置版用户列表，返回数量限制在 1 至 100 条。
     */
    @Operation(summary = "查询系统用户列表")
    @GetMapping
    public List<SystemUserView> list(
            @Parameter(description = "返回数量，范围 1 至 100")
            @RequestParam(defaultValue = "20") Integer limit) {
        // 1. 系统用户信息不属于游客公开数据，先校验登录身份。
        singleUserContext.requirePermission("SYSTEM_USER_READ");
        return systemUserService.list(limit);
    }

    /**
     * 按用户 ID 查询单个系统用户。
     */
    @Operation(summary = "查询系统用户详情")
    @GetMapping("/{id}")
    public SystemUserView get(
            @Parameter(description = "用户 ID", required = true)
            @PathVariable Long id) {
        // 1. 系统用户详情必须在认证边界内读取。
        singleUserContext.requirePermission("SYSTEM_USER_READ");
        return systemUserService.get(id);
    }
}
