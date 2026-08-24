package com.bdlh.runtime.security;

import com.bdlh.runtime.entity.User;
import com.bdlh.runtime.mapper.UserMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthServiceTest {

    private final UserMapper userMapper = mock(UserMapper.class);
    private final JwtTokenProvider tokenProvider = mock(JwtTokenProvider.class);
    private final AuthorizationService authorizationService = mock(AuthorizationService.class);
    private final AuthService service = new AuthService(userMapper, tokenProvider, authorizationService);

    @Test
    void shouldNormalizeUsernameHashPasswordAndAssignDefaultRoleOnRegistration() {
        when(userMapper.selectOne(any())).thenReturn(null);
        doAnswer(invocation -> {
            ((User) invocation.getArgument(0)).setId(8L);
            return 1;
        }).when(userMapper).insert(any(User.class));
        when(tokenProvider.createToken(8L)).thenReturn("jwt-token");

        AuthService.AuthResponse response = service.register("  Alice_01  ", "secure-pass");

        assertThat(response).isEqualTo(new AuthService.AuthResponse("jwt-token", 8L, "alice_01"));
        var inserted = org.mockito.ArgumentCaptor.forClass(User.class);
        verify(userMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getUsername()).isEqualTo("alice_01");
        assertThat(inserted.getValue().getPasswordHash()).doesNotContain("secure-pass");
        verify(authorizationService).assignDefaultRole(8L);
    }

    @Test
    void shouldRejectInvalidNewUsernameAndPassword() {
        assertThatThrownBy(() -> service.register("12bad", "secure-pass"))
                .isInstanceOf(AuthService.InvalidRegistrationException.class);
        assertThatThrownBy(() -> service.register("alice", "short"))
                .isInstanceOf(AuthService.InvalidRegistrationException.class);
    }

    @Test
    void shouldReturnOnlyMinimalCurrentUserProfile() {
        User user = new User();
        user.setId(7L);
        user.setUsername("sw_example22");
        user.setPasswordHash("not-exposed");
        when(userMapper.selectById(7L)).thenReturn(user);

        AuthService.UserProfile profile = service.profile(7L);

        assertThat(profile.userId()).isEqualTo(7L);
        assertThat(profile.username()).isEqualTo("sw_example22");
        assertThat(profile.toString()).doesNotContain("not-exposed");
    }
}
