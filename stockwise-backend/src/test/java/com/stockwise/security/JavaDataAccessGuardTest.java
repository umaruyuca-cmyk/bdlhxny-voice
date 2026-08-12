package com.stockwise.security;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.AfterEach;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class JavaDataAccessGuardTest {

    private final SingleUserContext context = mock(SingleUserContext.class);

    @AfterEach
    void clearRequestContext() {
        RequestContextHolder.resetRequestAttributes();
    }

    @Test
    void shouldUseAuthenticatedUserAndRejectCrossUserRead() {
        when(context.authenticatedUserId()).thenReturn(7L);
        JavaDataAccessGuard guard = new JavaDataAccessGuard(context, true, "");

        assertThat(guard.resolveUserId(7L)).isEqualTo(7L);
        assertThatThrownBy(() -> guard.resolveUserId(8L))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> assertThat(error.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN));
    }

    @Test
    void shouldRequireCredentialWhenProductionBoundaryIsEnabled() {
        when(context.authenticatedUserId()).thenReturn(null);
        JavaDataAccessGuard guard = new JavaDataAccessGuard(context, true, "");

        assertThatThrownBy(() -> guard.resolveUserId(null))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> assertThat(error.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED));
    }

    @Test
    void shouldAllowConfiguredSingleUserFallbackInDevelopment() {
        when(context.authenticatedUserId()).thenReturn(null);
        when(context.userId()).thenReturn(1L);
        JavaDataAccessGuard guard = new JavaDataAccessGuard(context, false, "");

        assertThat(guard.resolveUserId(null)).isEqualTo(1L);
    }

    @Test
    void shouldAllowInternalPythonRuntimeToReadTheVerifiedRequestedUser() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-Internal-Token", "service-secret");
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        JavaDataAccessGuard guard = new JavaDataAccessGuard(context, true, "service-secret");

        assertThat(guard.resolveUserId(42L)).isEqualTo(42L);
        assertThatThrownBy(() -> guard.resolveUserId(null))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> assertThat(error.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST));
    }
}
