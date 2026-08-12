package com.stockwise.api;

import com.stockwise.dto.AccountSnapshotResponse;
import com.stockwise.dto.DataAccessMetadata;
import com.stockwise.dto.PortfolioPositionsResponse;
import com.stockwise.dto.RiskProfileResponse;
import com.stockwise.dto.TransactionHistoryResponse;
import com.stockwise.security.JavaDataAccessGuard;
import com.stockwise.service.JavaDataQueryService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;

import java.time.OffsetDateTime;
import java.math.BigDecimal;
import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.assertj.core.api.Assertions.assertThat;

class JavaDataApiContractTest {

    private final JavaDataAccessGuard guard = mock(JavaDataAccessGuard.class);
    private final JavaDataQueryService service = mock(JavaDataQueryService.class);
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.standaloneSetup(
                new PortfolioDataController(guard, service),
                new UserRiskProfileController(guard, service))
                .build();
        when(guard.resolveUserId(7L)).thenReturn(7L);
    }

    @Test
    void shouldExposeAllFourPythonAdapterPaths() throws Exception {
        DataAccessMetadata metadata = DataAccessMetadata.of(
                7L, "SUCCESS", null, OffsetDateTime.parse("2026-08-09T00:00:00Z"));
        PortfolioPositionsResponse.Position position = new PortfolioPositionsResponse.Position(
                "600519", "贵州茅台", "stock", new BigDecimal("100"),
                new BigDecimal("1500"), null, null, null, null);
        when(service.positions(7L)).thenReturn(new PortfolioPositionsResponse(metadata, List.of(position)));
        when(service.account(7L)).thenReturn(new AccountSnapshotResponse(metadata, "CNY", null, null, null));
        when(service.transactions(7L, null)).thenReturn(new TransactionHistoryResponse(metadata, List.of()));
        when(service.riskProfile(7L)).thenReturn(new RiskProfileResponse(metadata, null, null, List.of(), List.of()));

        mvc.perform(get("/api/portfolio/positions").param("user_id", "7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.metadata.authorization_scope").value("SELF"))
                .andExpect(jsonPath("$.positions[0].cost_price").value(1500))
                .andExpect(jsonPath("$.positions[0].quantity").value(100));
        mvc.perform(get("/api/portfolio/account").param("user_id", "7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.currency").value("CNY"));
        mvc.perform(get("/api/portfolio/transactions").param("user_id", "7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.transactions").isArray());
        mvc.perform(get("/api/user/risk-profile").param("user_id", "7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.metadata.query_status").value("SUCCESS"));
    }

    @Test
    void javaDataControllersMustRemainReadOnly() {
        for (Class<?> controller : List.of(PortfolioDataController.class, UserRiskProfileController.class)) {
            for (var method : controller.getDeclaredMethods()) {
                assertThat(method.isAnnotationPresent(GetMapping.class)).isTrue();
                assertThat(method.isAnnotationPresent(PostMapping.class)).isFalse();
                assertThat(method.isAnnotationPresent(PutMapping.class)).isFalse();
                assertThat(method.isAnnotationPresent(PatchMapping.class)).isFalse();
                assertThat(method.isAnnotationPresent(DeleteMapping.class)).isFalse();
            }
        }
    }
}
