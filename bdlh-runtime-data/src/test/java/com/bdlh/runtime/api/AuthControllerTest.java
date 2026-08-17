package com.bdlh.runtime.api;

import com.bdlh.runtime.security.AuthService;
import com.bdlh.runtime.security.SingleUserContext;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AuthControllerTest {

    private final AuthService authService = mock(AuthService.class);
    private final SingleUserContext userContext = mock(SingleUserContext.class);
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.standaloneSetup(new AuthController(authService, userContext)).build();
    }

    @Test
    void shouldReturnCurrentAuthenticatedProfile() throws Exception {
        when(userContext.requireAuthenticatedUserId()).thenReturn(9L);
        when(authService.profile(9L)).thenReturn(new AuthService.UserProfile(9L, "sw_account22", null));

        mvc.perform(get("/api/v1/auth/me"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value(9))
                .andExpect(jsonPath("$.username").value("sw_account22"));
    }

    @Test
    void shouldCreateAccountOnValidRegistration() throws Exception {
        when(authService.register("alice_01", "secure-pass")).thenReturn(
                new AuthService.AuthResponse("jwt-token", 9L, "alice_01"));

        mvc.perform(post("/api/v1/auth/register")
                        .contentType("application/json")
                        .content("{\"username\":\"alice_01\",\"password\":\"secure-pass\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.token").value("jwt-token"))
                .andExpect(jsonPath("$.userId").value(9));
    }

    @Test
    void shouldReturnConflictForDuplicateUsername() throws Exception {
        when(authService.register("alice_01", "secure-pass"))
                .thenThrow(new AuthService.UsernameAlreadyExistsException());

        mvc.perform(post("/api/v1/auth/register")
                        .contentType("application/json")
                        .content("{\"username\":\"alice_01\",\"password\":\"secure-pass\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").value("用户名已存在"));
    }
}
