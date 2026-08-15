package com.bdlh.runtime.security;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

/**
 * 验证单用户回退和登录用户不会相互混淆。
 */
class SingleUserContextTest {

    private final SingleUserContext context = new SingleUserContext(1L, mock(AuthorizationService.class));

    @AfterEach
    void clearRequestContext() {
        RequestContextHolder.resetRequestAttributes();
    }

    @Test
    void shouldRequireLoginForProtectedRequestWithoutJwt() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));

        assertThatThrownBy(context::requireAuthenticatedUserId)
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("请先登录");
        assertThat(context.userId()).isEqualTo(1L);
    }

    @Test
    void shouldUseJwtUserWhenPresent() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute(JwtAuthenticationFilter.USER_ID_ATTRIBUTE, 42L);
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));

        assertThat(context.requireAuthenticatedUserId()).isEqualTo(42L);
        assertThat(context.userId()).isEqualTo(42L);
    }
}
