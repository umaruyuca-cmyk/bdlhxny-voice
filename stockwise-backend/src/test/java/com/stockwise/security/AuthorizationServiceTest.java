package com.stockwise.security;

import com.stockwise.mapper.AuthorizationMapper;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证权限码由服务端 RBAC 查询决定，拒绝结果统一为 403。
 */
class AuthorizationServiceTest {

    @Test
    void shouldRequirePermissionFromMapper() {
        AuthorizationMapper mapper = mock(AuthorizationMapper.class);
        when(mapper.hasPermission(7L, "AGENT_RUN_READ")).thenReturn(false);
        AuthorizationService service = new AuthorizationService(mapper);

        assertThatThrownBy(() -> service.requirePermission(7L, "AGENT_RUN_READ"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("缺少权限");
        verify(mapper).hasPermission(7L, "AGENT_RUN_READ");
    }
}
