package com.bdlh.runtime.security;

import at.favre.lib.crypto.bcrypt.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.bdlh.runtime.entity.User;
import com.bdlh.runtime.mapper.UserMapper;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Locale;
import java.util.regex.Pattern;

/**
 * 用户认证服务：注册、登录。密码使用 BCrypt 加盐哈希，不存储明文。
 */
@Service
public class AuthService {

    private static final int BCRYPT_COST = 12;
    private static final int USERNAME_MAX_LENGTH = 32;
    private static final int PASSWORD_MIN_LENGTH = 8;
    private static final int PASSWORD_MAX_LENGTH = 128;
    private static final Pattern USERNAME_PATTERN = Pattern.compile("^[a-z][a-z0-9_]{2,31}$");

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
    @Transactional
    public AuthResponse register(String username, String password) {
        username = normalizeUsernameForRegistration(username);
        validateNewPassword(password);
        // 1. 检查用户名是否已存在
        User existing = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, username));
        if (existing != null) {
            throw new UsernameAlreadyExistsException();
        }

        // 2. BCrypt 哈希密码后写入 MySQL
        User user = new User();
        user.setUsername(username);
        user.setPasswordHash(BCrypt.withDefaults().hashToString(BCRYPT_COST, password.toCharArray()));
        try {
            userMapper.insert(user);
        } catch (DuplicateKeyException exception) {
            throw new UsernameAlreadyExistsException();
        }

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
        username = normalizeUsernameForLogin(username);
        if (username == null || password == null || password.isBlank() || password.length() > PASSWORD_MAX_LENGTH) {
            throw new InvalidCredentialsException();
        }
        User user = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, username));
        if (user == null) {
            throw new InvalidCredentialsException();
        }

        BCrypt.Result result = BCrypt.verifyer().verify(password.toCharArray(), user.getPasswordHash());
        if (!result.verified) {
            throw new InvalidCredentialsException();
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

    private String normalizeUsernameForRegistration(String username) {
        String normalized = normalizeUsername(username);
        if (normalized == null || normalized.length() > USERNAME_MAX_LENGTH
                || !USERNAME_PATTERN.matcher(normalized).matches()) {
            throw new InvalidRegistrationException(
                    "用户名须为 3–32 位小写字母、数字或下划线，且以字母开头");
        }
        return normalized;
    }

    private String normalizeUsernameForLogin(String username) {
        String normalized = normalizeUsername(username);
        return normalized == null || normalized.length() > USERNAME_MAX_LENGTH ? null : normalized;
    }

    private String normalizeUsername(String username) {
        if (username == null) {
            return null;
        }
        String normalized = username.trim().toLowerCase(Locale.ROOT);
        return normalized.isEmpty() ? null : normalized;
    }

    private void validateNewPassword(String password) {
        if (password == null || password.isBlank() || password.length() < PASSWORD_MIN_LENGTH
                || password.length() > PASSWORD_MAX_LENGTH) {
            throw new InvalidRegistrationException("密码长度须为 8–128 位，且不能全为空白字符");
        }
    }

    /**
     * 登录/注册成功返回的结构。
     */
    public record AuthResponse(String token, Long userId, String username) {
    }

    public record UserProfile(Long userId, String username, java.time.LocalDateTime createdAt) {
    }

    /**
     * 认证领域异常的基类。
     */
    public static class AuthException extends RuntimeException {
        public AuthException(String message) {
            super(message);
        }
    }

    public static final class InvalidRegistrationException extends AuthException {
        public InvalidRegistrationException(String message) {
            super(message);
        }
    }

    public static final class UsernameAlreadyExistsException extends AuthException {
        public UsernameAlreadyExistsException() {
            super("用户名已存在");
        }
    }

    public static final class InvalidCredentialsException extends AuthException {
        public InvalidCredentialsException() {
            super("用户名或密码错误");
        }
    }
}
