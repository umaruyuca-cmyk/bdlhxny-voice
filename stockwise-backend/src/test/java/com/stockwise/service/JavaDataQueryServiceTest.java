package com.stockwise.service;

import com.stockwise.dto.AccountSnapshotResponse;
import com.stockwise.dto.PortfolioPositionsResponse;
import com.stockwise.dto.RiskProfileResponse;
import com.stockwise.dto.TransactionHistoryResponse;
import com.stockwise.entity.PortfolioPosition;
import com.stockwise.entity.PortfolioTransaction;
import com.stockwise.entity.UserConfig;
import com.stockwise.mapper.PortfolioPositionMapper;
import com.stockwise.mapper.PortfolioTransactionMapper;
import com.stockwise.mapper.UserConfigMapper;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class JavaDataQueryServiceTest {

    private final PortfolioPositionMapper positionMapper = mock(PortfolioPositionMapper.class);
    private final PortfolioTransactionMapper transactionMapper = mock(PortfolioTransactionMapper.class);
    private final UserConfigMapper configMapper = mock(UserConfigMapper.class);
    private final JavaDataQueryService service = new JavaDataQueryService(
            positionMapper, transactionMapper, configMapper);

    @Test
    void shouldReturnSanitizedPositionsWithMetadata() {
        PortfolioPosition entity = new PortfolioPosition();
        entity.setId(99L);
        entity.setUserId(7L);
        entity.setCode("600519");
        entity.setName("贵州茅台");
        entity.setAssetType("stock");
        entity.setShares(new BigDecimal("100"));
        entity.setAvgCost(new BigDecimal("1500"));
        entity.setActive(true);
        entity.setUpdatedAt(OffsetDateTime.parse("2026-08-08T10:00:00Z"));
        when(positionMapper.selectList(any())).thenReturn(List.of(entity));

        PortfolioPositionsResponse response = service.positions(7L);

        assertThat(response.metadata().userId()).isEqualTo(7L);
        assertThat(response.metadata().authorizationScope()).isEqualTo("SELF");
        assertThat(response.metadata().queryStatus()).isEqualTo("SUCCESS");
        assertThat(response.positions()).singleElement().satisfies(position -> {
            assertThat(position.symbol()).isEqualTo("600519");
            assertThat(position.quantity()).isEqualByComparingTo("100");
        });
        assertThat(response.toString()).doesNotContain("userId=99", "id=99");
    }

    @Test
    void shouldMarkMissingAccountAsNotConfiguredWithoutInventingValues() {
        when(configMapper.selectById(7L)).thenReturn(null);

        AccountSnapshotResponse response = service.account(7L);

        assertThat(response.metadata().queryStatus()).isEqualTo("NOT_CONFIGURED");
        assertThat(response.cash()).isNull();
        assertThat(response.monthlyBudget()).isNull();
        assertThat(response.cashReserveRatio()).isNull();
    }

    @Test
    void shouldReturnReadOnlyTransactionHistory() {
        PortfolioTransaction entity = new PortfolioTransaction();
        entity.setId(12L);
        entity.setUserId(7L);
        entity.setSymbol("600519");
        entity.setTransactionType("BUY");
        entity.setQuantity(new BigDecimal("100"));
        entity.setPrice(new BigDecimal("1500"));
        entity.setAmount(new BigDecimal("150000"));
        entity.setCurrency("CNY");
        entity.setTradeDate(LocalDate.of(2026, 8, 1));
        entity.setCreatedAt(OffsetDateTime.parse("2026-08-01T08:00:00Z"));
        when(transactionMapper.selectList(any())).thenReturn(List.of(entity));

        TransactionHistoryResponse response = service.transactions(7L, 1000);

        assertThat(response.metadata().queryStatus()).isEqualTo("SUCCESS");
        assertThat(response.transactions()).singleElement().satisfies(transaction -> {
            assertThat(transaction.transactionId()).isEqualTo(12L);
            assertThat(transaction.transactionType()).isEqualTo("BUY");
        });
    }

    @Test
    void shouldParseConfiguredRiskProfileWithoutDefaults() {
        UserConfig config = new UserConfig();
        config.setUserId(7L);
        config.setRiskTolerance(" Conservative ");
        config.setCashReserveRatio(new BigDecimal("0.30"));
        config.setPreferredSectors("消费, 医药,消费");
        config.setForbiddenSymbols("300001, 688001");
        when(configMapper.selectById(7L)).thenReturn(config);

        RiskProfileResponse response = service.riskProfile(7L);

        assertThat(response.metadata().queryStatus()).isEqualTo("SUCCESS");
        assertThat(response.riskTolerance()).isEqualTo("conservative");
        assertThat(response.preferredSectors()).containsExactly("消费", "医药");
        assertThat(response.forbiddenSymbols()).containsExactly("300001", "688001");
    }
}
