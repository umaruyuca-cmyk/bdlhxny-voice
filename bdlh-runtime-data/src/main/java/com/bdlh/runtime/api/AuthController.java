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
     * 注册新用户，返回 JWT 令牌。
     */
    @PostMapping("/register")
    @ResponseStatus(HttpStatus.CREATED)
    public AuthService.AuthResponse register(@RequestBody AuthRequest request) {
        return authService.register(request == null ? null : request.username(),
                request == null ? null : request.password());
    }

    /**
     * 登录成功返回 JWT，失败返回 401。
     */
    @PostMapping("/login")
    public AuthService.AuthResponse login(@RequestBody AuthRequest request) {
        return authService.login(request == null ? null : request.username(),
                request == null ? null : request.password());
    }

    /** 用于前端恢复登录状态，不返回密码摘要或权限表。 */
    @GetMapping("/me")
    public AuthService.UserProfile me() {
        return authService.profile(singleUserContext.requireAuthenticatedUserId());
    }

    @ExceptionHandler(AuthService.InvalidRegistrationException.class)
    public ResponseEntity<Map<String, String>> handleInvalidRegistration(AuthService.InvalidRegistrationException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }

    @ExceptionHandler(AuthService.UsernameAlreadyExistsException.class)
    public ResponseEntity<Map<String, String>> handleDuplicateUsername(AuthService.UsernameAlreadyExistsException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("error", e.getMessage()));
    }

    @ExceptionHandler(AuthService.AuthException.class)
    public ResponseEntity<Map<String, String>> handleAuth(AuthService.AuthException e) {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(Map.of("error", e.getMessage()));
    }

    public record AuthRequest(String username, String password) {
    }
}
