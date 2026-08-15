package com.stockwise.service;

import com.stockwise.dto.FinancialProfileConfirmationResponse;
import com.stockwise.dto.FinancialProfileUpdateRequest;
import com.stockwise.dto.PortfolioPositionsUpdateRequest;
import com.stockwise.entity.FinancialProfileConfirmation;
import com.stockwise.entity.PortfolioPosition;
import com.stockwise.entity.UserConfig;
import com.stockwise.mapper.FinancialProfileConfirmationMapper;
import com.stockwise.mapper.PortfolioPositionMapper;
import com.stockwise.mapper.UserConfigMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class FinancialProfileCommandServiceTest {

    private final UserConfigMapper configMapper = mock(UserConfigMapper.class);
    private final PortfolioPositionMapper positionMapper = mock(PortfolioPositionMapper.class);
    private final FinancialProfileConfirmationMapper confirmationMapper =
            mock(FinancialProfileConfirmationMapper.class);
    private final FinancialProfileCommandService service = new FinancialProfileCommandService(
            configMapper, positionMapper, confirmationMapper);

    @Test
    void shouldConfirmProfileWithOptimisticVersionAndServerProvenance() {
        UserConfig existing = new UserConfig();
        existing.setUserId(7L);
        existing.setProfileVersion(2L);
        when(configMapper.selectById(7L)).thenReturn(existing);
        when(configMapper.update(any(), any())).thenReturn(1);
        when(confirmationMapper.selectOne(any())).thenReturn(null);

        FinancialProfileConfirmationResponse response = service.replaceFinancialProfile(
                7L, "profile-update-1", profileRequest(2L));

        assertThat(response.userId()).isEqualTo(7L);
        assertThat(response.profileVersion()).isEqualTo(3L);
        assertThat(response.dataMode()).isEqualTo("USER_CONFIRMED");
        assertThat(response.confirmationRef()).isNotBlank();
        assertThat(existing.getFinancialDataSource()).isEqualTo("USER_INPUT");
        assertThat(existing.getMaxLossTolerancePct()).isEqualByComparingTo("25");
        assertThat(existing.getProfileVersion()).isEqualTo(3L);

        ArgumentCaptor<FinancialProfileConfirmation> audit =
                ArgumentCaptor.forClass(FinancialProfileConfirmation.class);
        verify(confirmationMapper).insert((FinancialProfileConfirmation) audit.capture());
        assertThat(audit.getValue().getRequestFingerprint()).hasSize(64);
        assertThat(audit.getValue().getChangedFields()).contains("risk_profile.max_loss_tolerance_pct");
        assertThat(audit.getValue().getChangedFields()).doesNotContain("20000", "50000");
    }

    @Test
    void shouldReturnSameConfirmationForIdempotentReplayWithoutSecondWrite() {
        UserConfig existing = new UserConfig();
        existing.setUserId(7L);
        existing.setProfileVersion(0L);
        when(configMapper.selectById(7L)).thenReturn(existing);
        when(configMapper.update(any(), any())).thenReturn(1);
        AtomicReference<FinancialProfileConfirmation> stored = new AtomicReference<>();
        when(confirmationMapper.selectOne(any())).thenAnswer(ignored -> stored.get());
        when(confirmationMapper.insert((FinancialProfileConfirmation) any())).thenAnswer(invocation -> {
            stored.set(invocation.getArgument(0));
            return 1;
        });

        FinancialProfileConfirmationResponse first = service.replaceFinancialProfile(
                7L, "same-key", profileRequest(0L));
        FinancialProfileConfirmationResponse replay = service.replaceFinancialProfile(
                7L, "same-key", profileRequest(0L));

        assertThat(replay).isEqualTo(first);
        verify(configMapper).update(any(), any());
        verify(confirmationMapper).insert((FinancialProfileConfirmation) any());
    }

    @Test
    void shouldRejectStaleProfileVersionBeforeAnyMutation() {
        UserConfig existing = new UserConfig();
        existing.setUserId(7L);
        existing.setProfileVersion(4L);
        when(configMapper.selectById(7L)).thenReturn(existing);
        when(confirmationMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> service.replaceFinancialProfile(
                7L, "stale-key", profileRequest(3L)))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("版本冲突");

        verify(configMapper, never()).update(any(), any());
        verify(confirmationMapper, never()).insert((FinancialProfileConfirmation) any());
    }

    @Test
    void shouldReplacePositionsWithOneServerConfirmationAndDeactivateOmittedRows() {
        UserConfig config = new UserConfig();
        config.setUserId(7L);
        config.setProfileVersion(1L);
        when(configMapper.selectById(7L)).thenReturn(config);
        when(configMapper.update(any(), any())).thenReturn(1);
        when(confirmationMapper.selectOne(any())).thenReturn(null);

        PortfolioPosition omitted = new PortfolioPosition();
        omitted.setId(10L);
        omitted.setUserId(7L);
        omitted.setCode("000001");
        omitted.setActive(true);
        when(positionMapper.selectList(any())).thenReturn(List.of(omitted));

        PortfolioPositionsUpdateRequest request = new PortfolioPositionsUpdateRequest(
                1L,
                List.of(new PortfolioPositionsUpdateRequest.Position(
                        "600519", "贵州茅台", "stock", new BigDecimal("100"),
                        new BigDecimal("1500"), LocalDate.of(2024, 1, 2),
                        new BigDecimal("0.30"), "消费", "core", "SSE", "CNY")));

        FinancialProfileConfirmationResponse response = service.replacePositions(
                7L, "positions-key", request);

        assertThat(response.profileVersion()).isEqualTo(2L);
        assertThat(omitted.getActive()).isFalse();
        ArgumentCaptor<PortfolioPosition> inserted = ArgumentCaptor.forClass(PortfolioPosition.class);
        verify(positionMapper).insert((PortfolioPosition) inserted.capture());
        assertThat(inserted.getValue().getCode()).isEqualTo("600519");
        assertThat(inserted.getValue().getDataSource()).isEqualTo("USER_INPUT");
        assertThat(inserted.getValue().getSourceRef()).isEqualTo(response.confirmationRef());
        assertThat(inserted.getValue().getCurrency()).isEqualTo("CNY");
    }

    private FinancialProfileUpdateRequest profileRequest(long expectedVersion) {
        return new FinancialProfileUpdateRequest(
                expectedVersion,
                "CNY",
                new BigDecimal("20000"),
                "balanced",
                new BigDecimal("25"),
                new BigDecimal("50000"),
                new BigDecimal("10000"),
                90);
    }
}
