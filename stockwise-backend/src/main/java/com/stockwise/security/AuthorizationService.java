package com.stockwise.security;

import com.stockwise.mapper.AuthorizationMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * 统一执行基于角色的权限查询，避免控制器自行拼接用户和角色逻辑。
 */
@Service
public class AuthorizationService {

    private final AuthorizationMapper authorizationMapper;

    public AuthorizationService(AuthorizationMapper authorizationMapper) {
        this.authorizationMapper = authorizationMapper;
    }

    /**
     * 查询用户是否拥有指定权限码。
     */
    public boolean hasPermission(Long userId, String permissionCode) {
        if (userId == null || userId <= 0 || permissionCode == null || permissionCode.isBlank()) {
            return false;
        }
        return authorizationMapper.hasPermission(userId, permissionCode);
    }

    /**
     * 为新注册用户分配默认 USER 角色。
     */
    public void assignDefaultRole(Long userId) {
        if (userId == null || userId <= 0) {
            throw new IllegalArgumentException("用户ID无效，无法分配默认角色");
        }
        authorizationMapper.assignDefaultRole(userId);
    }

    /**
     * 要求指定用户拥有权限，否则返回统一 403。
     */
    public void requirePermission(Long userId, String permissionCode) {
        if (!hasPermission(userId, permissionCode)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "缺少权限: " + permissionCode);
        }
    }
}
