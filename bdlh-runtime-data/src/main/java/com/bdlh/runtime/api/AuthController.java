package com.bdlh.runtime.api;

import com.bdlh.runtime.security.AuthService;
import com.bdlh.runtime.security.SingleUserContext;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.ResponseStatus;

import java.util.Map;

/**
 * 用户认证接口：注册与登录。
 */
@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final AuthService authService;
    private final SingleUserContext singleUserContext;

    public AuthController(AuthService authService, SingleUserContext singleUserContext) {
        this.authService = authService;
        this.singleUserContext = singleUserContext;
    }

    /**
     * 无需填写资料的一键账号申请。响应中的初始密码只展示一次。
     */
    @PostMapping("/apply")
    @ResponseStatus(HttpStatus.CREATED)
    public AuthService.AccountApplicationResponse apply() {
        return authService.applyAccount();
    }

    /**
     * 注册新用户，返回 JWT 令牌。
     */
    @PostMapping("/register")
    public AuthService.AuthResponse register(@RequestBody AuthRequest request) {
        validate(request);
        return authService.register(request.username(), request.password());
    }

    /**
     * 登录成功返回 JWT，失败返回 401。
     */
    @PostMapping("/login")
    public AuthService.AuthResponse login(@RequestBody AuthRequest request) {
        validate(request);
        return authService.login(request.username(), request.password());
    }

    /** 用于前端恢复登录状态，不返回密码摘要或权限表。 */
    @GetMapping("/me")
    public AuthService.UserProfile me() {
        return authService.profile(singleUserContext.requireAuthenticatedUserId());
    }

    @ExceptionHandler(AuthService.AuthException.class)
    public ResponseEntity<Map<String, String>> handleAuth(AuthService.AuthException e) {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(Map.of("error", e.getMessage()));
    }

    private void validate(AuthRequest request) {
        if (request == null || request.username() == null || request.username().isBlank()) {
            throw new AuthService.AuthException("用户名不能为空");
        }
        if (request.password() == null || request.password().length() < 6) {
            throw new AuthService.AuthException("密码至少需要6位");
        }
    }

    public record AuthRequest(String username, String password) {
    }
}
