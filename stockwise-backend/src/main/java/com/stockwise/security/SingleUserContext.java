package com.stockwise.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

/**
 * 为当前请求提供用户身份，优先读取 JWT 解析的 userId，无 Token 时回退到单用户兼容ID；游客状态单独由 isGuest() 判断。
 */
@Component
public class SingleUserContext {

    private final long singleUserId;
    private final AuthorizationService authorizationService;

    public SingleUserContext(@Value("${stockwise.single-user.id:1}") long singleUserId,
                             AuthorizationService authorizationService) {
        if (singleUserId <= 0) {
            throw new IllegalArgumentException("stockwise.single-user.id 必须大于0");
        }
        this.singleUserId = singleUserId;
        this.authorizationService = authorizationService;
    }

    /**
     * 返回当前请求的用户ID。
     * 优先从 JWT Filter 注入的请求属性读取；异步线程或非 HTTP 上下文时使用配置的单用户 ID。
     */
    public long userId() {
        RequestAttributes attrs = RequestContextHolder.getRequestAttributes();
        if (attrs instanceof ServletRequestAttributes servletAttrs) {
            Object userIdObj = servletAttrs.getRequest()
                    .getAttribute(JwtAuthenticationFilter.USER_ID_ATTRIBUTE);
            if (userIdObj instanceof Long userId && userId > 0) {
                return userId;
            }
        }
        return singleUserId;
    }

    /**
     * 当前请求是否为游客。
     */
    public boolean isGuest() {
        RequestAttributes attrs = RequestContextHolder.getRequestAttributes();
        return attrs instanceof ServletRequestAttributes && authenticatedUserId() == null;
    }

    /**
     * 返回当前请求的已认证用户ID；游客和异步线程上下文返回 null。
     */
    public Long authenticatedUserId() {
        RequestAttributes attrs = RequestContextHolder.getRequestAttributes();
        if (attrs instanceof ServletRequestAttributes servletAttrs) {
            Object userIdObj = servletAttrs.getRequest()
                    .getAttribute(JwtAuthenticationFilter.USER_ID_ATTRIBUTE);
            if (userIdObj instanceof Long userId && userId > 0) {
                return userId;
            }
        }
        return null;
    }

    /**
     * 要求当前请求已登录，统一把未认证访问转换为 401。
     */
    public long requireAuthenticatedUserId() {
        Long userId = authenticatedUserId();
        if (userId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "请先登录");
        }
        return userId;
    }

    /**
     * 要求当前登录用户拥有指定 RBAC 权限。
     */
    public long requirePermission(String permissionCode) {
        long userId = requireAuthenticatedUserId();
        authorizationService.requirePermission(userId, permissionCode);
        return userId;
    }
}
