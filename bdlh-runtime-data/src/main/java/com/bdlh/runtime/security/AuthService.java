package com.bdlh.runtime.security;

import at.favre.lib.crypto.bcrypt.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.bdlh.runtime.entity.User;
import com.bdlh.runtime.mapper.UserMapper;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;

/**
 * 用户认证服务：注册、登录。密码使用 BCrypt 加盐哈希，不存储明文。
 */
@Service
public class AuthService {

    private static final int BCRYPT_COST = 12;
    private static final int ACCOUNT_GENERATION_ATTEMPTS = 8;
    private static final String USERNAME_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";
    private static final String PASSWORD_ALPHABET =
            "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789!@#$%";

    private final UserMapper userMapper;
    private final JwtTokenProvider jwtTokenProvider;
    private final AuthorizationService authorizationService;
    private final SecureRandom secureRandom = new SecureRandom();

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
    @Transactional
    public AuthResponse register(String username, String password) {
        username = normalizeUsername(username);
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
        try {
            userMapper.insert(user);
        } catch (DuplicateKeyException exception) {
            throw new AuthException("用户名已存在");
        }

        // 3. 新用户默认分配USER角色，权限从MySQL RBAC关系读取。
        authorizationService.assignDefaultRole(user.getId());
        // 4. 签发 JWT
        String token = jwtTokenProvider.createToken(user.getId());
        return new AuthResponse(token, user.getId(), user.getUsername());
    }

    /**
     * 一键申请账号：服务端生成唯一用户名和初始密码，并立即签发个人 JWT。
     * 初始密码只在本次响应中返回，数据库仍只保存 BCrypt 摘要。
     */
    @Transactional
    public AccountApplicationResponse applyAccount() {
        for (int attempt = 0; attempt < ACCOUNT_GENERATION_ATTEMPTS; attempt++) {
            String username = "sw_" + randomText(USERNAME_ALPHABET, 10);
            User existing = userMapper.selectOne(
                    new LambdaQueryWrapper<User>().eq(User::getUsername, username));
            if (existing != null) {
                continue;
            }
            String initialPassword = randomText(PASSWORD_ALPHABET, 16);
            User user = new User();
            user.setUsername(username);
            user.setPasswordHash(BCrypt.withDefaults().hashToString(
                    BCRYPT_COST, initialPassword.toCharArray()));
            try {
                userMapper.insert(user);
            } catch (DuplicateKeyException exception) {
                // 数据库唯一索引负责处理并发下极小概率的用户名碰撞。
                continue;
            }
            if (user.getId() == null || user.getId() <= 0) {
                throw new AuthException("账号创建失败，请重试");
            }
            authorizationService.assignDefaultRole(user.getId());
            String token = jwtTokenProvider.createToken(user.getId());
            return new AccountApplicationResponse(
                    token, user.getId(), username, initialPassword, true);
        }
        throw new AuthException("暂时无法生成唯一账号，请重试");
    }

    /**
     * 密码验证通过后签发 JWT。
     */
    public AuthResponse login(String username, String password) {
        username = normalizeUsername(username);
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

    /** 查询当前登录用户的最小公开资料。 */
    public UserProfile profile(Long userId) {
        User user = userId == null ? null : userMapper.selectById(userId);
        if (user == null) {
            throw new AuthException("用户不存在");
        }
        return new UserProfile(user.getId(), user.getUsername(), user.getCreatedAt());
    }

    private String normalizeUsername(String username) {
        return username == null ? "" : username.trim().toLowerCase();
    }

    private String randomText(String alphabet, int length) {
        StringBuilder result = new StringBuilder(length);
        for (int index = 0; index < length; index++) {
            result.append(alphabet.charAt(secureRandom.nextInt(alphabet.length())));
        }
        return result.toString();
    }

    /**
     * 登录/注册成功返回的结构。
     */
    public record AuthResponse(String token, Long userId, String username) {
    }

    public record AccountApplicationResponse(
            String token,
            Long userId,
            String username,
            String initialPassword,
            boolean passwordShownOnce) {
    }

    public record UserProfile(Long userId, String username, java.time.LocalDateTime createdAt) {
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
