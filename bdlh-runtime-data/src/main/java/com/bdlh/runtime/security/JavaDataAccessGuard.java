package com.bdlh.runtime.security;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * Java Data API 的用户隔离边界。
 *
 * <p>生产环境可强制要求 JWT；开发期仍允许回退到单用户工作站身份。无论哪种模式，
 * 请求参数都不能越权读取其他用户。</p>
 */
@Component
public class JavaDataAccessGuard {

    private final SingleUserContext singleUserContext;
    private final boolean requireAuthenticated;
    private final String internalToken;

    public JavaDataAccessGuard(
            SingleUserContext singleUserContext,
            @Value("${bdlh_runtime.java-data.require-authenticated:false}") boolean requireAuthenticated,
            @Value("${bdlh_runtime.java-data.internal-token:}") String internalToken) {
        this.singleUserContext = singleUserContext;
        this.requireAuthenticated = requireAuthenticated;
        this.internalToken = internalToken == null ? "" : internalToken;
    }

    public long resolveUserId(Long requestedUserId) {
        if (hasValidInternalToken()) {
            // 0 = 游客（与 Python GUEST_USER_ID 对齐）；负值仍非法。
            if (requestedUserId == null || requestedUserId < 0) {
                throw new ResponseStatusException(
                        HttpStatus.BAD_REQUEST, "内部服务调用必须指定有效 user_id");
            }
            return requestedUserId;
        }
        Long authenticatedUserId = singleUserContext.authenticatedUserId();
        if (requireAuthenticated && authenticatedUserId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Java Data API 需要有效身份凭证");
        }
        long effectiveUserId = authenticatedUserId != null
                ? authenticatedUserId
                : singleUserContext.userId();
        if (requestedUserId != null && requestedUserId.longValue() != effectiveUserId) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "不得读取其他用户的数据");
        }
        return effectiveUserId;
    }

    /** Scheduler/relay administration must never be callable with an end-user identity alone. */
    public void requireInternalService() {
        if (!hasValidInternalToken()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "该内部操作需要服务凭证");
        }
    }

    private boolean hasValidInternalToken() {
        if (internalToken.isBlank()) {
            return false;
        }
        var attributes = RequestContextHolder.getRequestAttributes();
        if (!(attributes instanceof ServletRequestAttributes servletAttributes)) {
            return false;
        }
        String supplied = servletAttributes.getRequest().getHeader("X-Internal-Token");
        if (supplied == null || supplied.isBlank()) {
            return false;
        }
        return MessageDigest.isEqual(
                internalToken.getBytes(StandardCharsets.UTF_8),
                supplied.getBytes(StandardCharsets.UTF_8));
    }
}
