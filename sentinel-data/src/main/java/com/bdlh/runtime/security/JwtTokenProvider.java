package com.bdlh.runtime.security;

import io.jsonwebtoken.Jwts;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.util.Date;

/**
 * JWT 令牌签发与校验。HMAC-SHA256 签名，7天过期。
 */
@Component
public class JwtTokenProvider {

    private final SecretKey key;
    private final long expirationMs;

    public JwtTokenProvider(
            @Value("${bdlh_runtime.jwt.secret:}") String secret,
            @Value("${bdlh_runtime.jwt.expiration-days:7}") int expirationDays) {
        byte[] keyBytes = (secret.isBlank()
                ? "BDLH Agent Runtime-Default-JWT-Key-2026-Must-Override-In-Production!!!"
                : secret).getBytes(StandardCharsets.UTF_8);
        this.key = new SecretKeySpec(keyBytes, "HmacSHA256");
        this.expirationMs = Math.max(1, expirationDays) * 86_400_000L;
    }

    /**
     * 签发包含 userId 的 JWT 令牌。
     */
    public String createToken(Long userId) {
        Date now = new Date();
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .issuedAt(now)
                .expiration(new Date(now.getTime() + expirationMs))
                .signWith(key)
                .compact();
    }

    /**
     * 校验并解析 token 中的 userId，失败返回 null。
     */
    public Long validate(String token) {
        if (token == null || token.isBlank()) {
            return null;
        }
        try {
            String subject = Jwts.parser()
                    .verifyWith(key)
                    .build()
                    .parseSignedClaims(token.trim())
                    .getPayload()
                    .getSubject();
            return Long.parseLong(subject);
        } catch (Exception ignored) {
            return null;
        }
    }
}
