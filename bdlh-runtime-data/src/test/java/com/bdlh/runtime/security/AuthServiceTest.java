package com.bdlh.runtime.security;

import at.favre.lib.crypto.bcrypt.BCrypt;
import com.bdlh.runtime.entity.User;
import com.bdlh.runtime.mapper.UserMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
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
    void shouldApplyAccountWithoutUserInputAndReturnPasswordOnlyOnce() {
        when(userMapper.selectOne(any())).thenReturn(null);
        doAnswer(invocation -> {
            User user = invocation.getArgument(0);
            user.setId(101L);
            return 1;
        }).when(userMapper).insert(any(User.class));
        when(tokenProvider.createToken(101L)).thenReturn("jwt-token");

        AuthService.AccountApplicationResponse response = service.applyAccount();

        assertThat(response.userId()).isEqualTo(101L);
        assertThat(response.username()).matches("sw_[a-z2-9]{10}");
        assertThat(response.initialPassword()).hasSize(16);
        assertThat(response.passwordShownOnce()).isTrue();
        assertThat(response.token()).isEqualTo("jwt-token");
        verify(authorizationService).assignDefaultRole(101L);

        var inserted = org.mockito.ArgumentCaptor.forClass(User.class);
        verify(userMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getPasswordHash()).doesNotContain(response.initialPassword());
        assertThat(BCrypt.verifyer().verify(
                response.initialPassword().toCharArray(), inserted.getValue().getPasswordHash()).verified)
                .isTrue();
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
