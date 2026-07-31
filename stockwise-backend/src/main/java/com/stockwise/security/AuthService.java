package com.stockwise.security;

import at.favre.lib.crypto.bcrypt.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.stockwise.entity.User;
import com.stockwise.mapper.UserMapper;
import org.springframework.stereotype.Service;

/**
 * 用户认证服务：注册、登录。密码使用 BCrypt 加盐哈希，不存储明文。
 */
@Service
public class AuthService {

    private static final int BCRYPT_COST = 12;

    private final UserMapper userMapper;
    private final JwtTokenProvider jwtTokenProvider;
    private final AuthorizationService authorizationService;

    public AuthService(UserMapper userMapper,
                       JwtTokenProvider jwtTokenProvider,
                       AuthorizationService authorizationService) {
        this.userMapper = userMapper;
        this.jwtTokenProvider = jwtTokenProvider;
        this.authorizationService = authorizationService;
    }

    /**
     * 注册新用户，返回 JWT 令牌。
     */
    public AuthResponse register(String username, String password) {
        // 1. 检查用户名是否已存在
        User existing = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, username));
        if (existing != null) {
            throw new AuthException("用户名已存在");
        }

        // 2. BCrypt 哈希密码后写入 MySQL
        User user = new User();
        user.setUsername(username);
        user.setPasswordHash(BCrypt.withDefaults().hashToString(BCRYPT_COST, password.toCharArray()));
        userMapper.insert(user);

        // 3. 新用户默认分配USER角色，权限从MySQL RBAC关系读取。
        authorizationService.assignDefaultRole(user.getId());
        // 4. 签发 JWT
        String token = jwtTokenProvider.createToken(user.getId());
        return new AuthResponse(token, user.getId(), user.getUsername());
    }

    /**
     * 密码验证通过后签发 JWT。
     */
    public AuthResponse login(String username, String password) {
        User user = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, username));
        if (user == null) {
            throw new AuthException("用户名或密码错误");
        }

        BCrypt.Result result = BCrypt.verifyer().verify(password.toCharArray(), user.getPasswordHash());
        if (!result.verified) {
            throw new AuthException("用户名或密码错误");
        }

        String token = jwtTokenProvider.createToken(user.getId());
        return new AuthResponse(token, user.getId(), user.getUsername());
    }

    /**
     * 登录/注册成功返回的结构。
     */
    public record AuthResponse(String token, Long userId, String username) {
    }

    /**
     * 认证相关业务异常，Controller 全局捕获后返回 401。
     */
    public static class AuthException extends RuntimeException {
        public AuthException(String message) {
            super(message);
        }
    }
}
