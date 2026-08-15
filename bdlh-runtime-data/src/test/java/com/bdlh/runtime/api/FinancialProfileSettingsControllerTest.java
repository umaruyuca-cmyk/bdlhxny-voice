package com.bdlh.runtime.api;

import com.bdlh.runtime.dto.FinancialProfileConfirmationResponse;
import com.bdlh.runtime.dto.FinancialProfileUpdateRequest;
import com.bdlh.runtime.security.SingleUserContext;
import com.bdlh.runtime.service.FinancialProfileCommandService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class FinancialProfileSettingsControllerTest {

    private final SingleUserContext userContext = mock(SingleUserContext.class);
    private final FinancialProfileCommandService commandService = mock(FinancialProfileCommandService.class);
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.standaloneSetup(
                new FinancialProfileSettingsController(userContext, commandService)).build();
    }

    @Test
    void shouldBindAuthenticatedUserAndNeverAcceptClientUserId() throws Exception {
        when(userContext.requireAuthenticatedUserId()).thenReturn(7L);
        when(commandService.replaceFinancialProfile(eq(7L), eq("profile-1"), any()))
                .thenReturn(new FinancialProfileConfirmationResponse(
                        7L, 2L, "USER_CONFIRMED", "server-ref",
                        OffsetDateTime.parse("2026-08-10T00:00:00Z")));

        mvc.perform(put("/api/v1/user/financial-profile")
                        .header("Idempotency-Key", "profile-1")
                        .contentType("application/json")
                        .content("""
                                {
                                  "expected_profile_version": 1,
                                  "currency": "CNY",
                                  "cash": 20000,
                                  "risk_tolerance": "balanced",
                                  "max_loss_tolerance_pct": 25,
                                  "liquid_assets": 50000,
                                  "near_term_cash_needs": 10000,
                                  "near_term_cash_needs_horizon_days": 90
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.user_id").value(7))
                .andExpect(jsonPath("$.profile_version").value(2))
                .andExpect(jsonPath("$.data_mode").value("USER_CONFIRMED"))
                .andExpect(jsonPath("$.confirmation_ref").value("server-ref"));

        verify(commandService).replaceFinancialProfile(eq(7L), eq("profile-1"), any());
    }

    @Test
    void shouldRejectUnauthenticatedSettingsWrite() throws Exception {
        when(userContext.requireAuthenticatedUserId())
                .thenThrow(new ResponseStatusException(HttpStatus.UNAUTHORIZED, "请先登录"));

        mvc.perform(put("/api/v1/user/portfolio-positions")
                        .header("Idempotency-Key", "positions-1")
                        .contentType("application/json")
                        .content("{\"expected_profile_version\":0,\"positions\":[]}"))
                .andExpect(status().isUnauthorized());
    }
}
