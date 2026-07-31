package com.stockwise.security;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * 为未登录浏览器签发匿名主体，并只向业务层暴露不可逆哈希。
 */
@Component
public class GuestIdentityService {

    static final String COOKIE_NAME = "stockwise_guest";
    private static final int COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60;
    private static final Pattern VALID_GUEST_ID = Pattern.compile("[a-f0-9]{32}");

    /**
     * 复用合法游客 Cookie；首次访问时签发新 Cookie，并返回用于 Redis Key 的 SHA-256 哈希。
     */
    public String resolveSubjectHash(HttpServletRequest request, HttpServletResponse response) {
        String guestId = readGuestId(request);
        if (guestId == null) {
            // 1. 随机游客ID只保存在浏览器Cookie中，服务端存储仅使用其哈希。
            guestId = UUID.randomUUID().toString().replace("-", "");
            response.addHeader(HttpHeaders.SET_COOKIE, buildSetCookie(request, guestId));
        }
        // 2. 哈希后再交给配额模块，避免Redis中出现可直接复用的原始游客ID。
        return sha256(guestId);
    }

    private String readGuestId(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) {
            return null;
        }
        for (Cookie cookie : cookies) {
            if (COOKIE_NAME.equals(cookie.getName())
                    && cookie.getValue() != null
                    && VALID_GUEST_ID.matcher(cookie.getValue()).matches()) {
                return cookie.getValue();
            }
        }
        return null;
    }

    private String buildSetCookie(HttpServletRequest request, String guestId) {
        StringBuilder value = new StringBuilder()
                .append(COOKIE_NAME).append('=').append(guestId)
                .append("; Path=/; Max-Age=").append(COOKIE_MAX_AGE_SECONDS)
                .append("; HttpOnly; SameSite=Lax");
        if (isSecure(request)) {
            value.append("; Secure");
        }
        return value.toString();
    }

    private boolean isSecure(HttpServletRequest request) {
        if (request.isSecure()) {
            return true;
        }
        String forwardedProto = request.getHeader("X-Forwarded-Proto");
        return forwardedProto != null
                && "https".equalsIgnoreCase(forwardedProto.split(",", 2)[0].trim());
    }

    private String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("当前JVM不支持SHA-256", error);
        }
    }
}
