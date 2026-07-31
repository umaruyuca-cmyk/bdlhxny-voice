package com.stockwise.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 从 Authorization Header 提取 JWT 并反解 userId，写入请求属性供 SingleUserContext 读取。
 * 不依赖 Spring Security，成功解析设 userId，失败放行当游客。
 */
@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    static final String USER_ID_ATTRIBUTE = "stockwise.userId";

    private final JwtTokenProvider jwtTokenProvider;

    public JwtAuthenticationFilter(JwtTokenProvider jwtTokenProvider) {
        this.jwtTokenProvider = jwtTokenProvider;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain)
            throws ServletException, IOException {
        // 1. 从 Authorization 头提取 Bearer Token
        String header = request.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")) {
            Long userId = jwtTokenProvider.validate(header.substring(7));
            if (userId != null) {
                request.setAttribute(USER_ID_ATTRIBUTE, userId);
            }
        }
        // 2. Token 不存在或无效时继续作为游客处理
        chain.doFilter(request, response);
    }

    @Bean
    public FilterRegistrationBean<JwtAuthenticationFilter> jwtFilterRegistration(
            JwtAuthenticationFilter filter) {
        FilterRegistrationBean<JwtAuthenticationFilter> registration = new FilterRegistrationBean<>();
        registration.setFilter(filter);
        registration.addUrlPatterns("/api/*");
        registration.setOrder(0);
        return registration;
    }
}
