package com.bdlh.runtime.service;

import com.bdlh.runtime.entity.PortfolioPosition;
import com.bdlh.runtime.entity.UserConfig;
import com.bdlh.runtime.mapper.PortfolioPositionMapper;
import com.bdlh.runtime.mapper.UserConfigMapper;
import com.bdlh.runtime.tool.PortfolioAnalysisInput;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 验证组合分析只装载当前用户的真实业务事实，并在数据缺失时中止分析。
 */
class UserPortfolioServiceTest {

    private final PortfolioPositionMapper positionMapper = mock(PortfolioPositionMapper.class);
    private final UserConfigMapper configMapper = mock(UserConfigMapper.class);
    private final UserPortfolioService service = new UserPortfolioService(positionMapper, configMapper);

    @Test
    void shouldBuildSanitizedPortfolioSnapshot() {
        UserConfig config = new UserConfig();
        config.setUserId(7L);
        config.setMonthlyBudget(5_000);
        config.setCash(new BigDecimal("12000"));
        config.setCashReserveRatio(new BigDecimal("0.10"));
        when(configMapper.selectById(7L)).thenReturn(config);

        PortfolioPosition position = new PortfolioPosition();
        position.setId(99L);
        position.setUserId(7L);
        position.setCode("588200");
        position.setName("科创芯片ETF");
        position.setAssetType("etf");
        position.setAvgCost(new BigDecimal("1.20"));
        position.setShares(new BigDecimal("1000"));
        position.setBuyDate(LocalDate.of(2026, 1, 2));
        position.setTargetWeight(new BigDecimal("0.30"));
        position.setSector("半导体");
        position.setRiskRole("进攻");
        position.setActive(true);
        when(positionMapper.selectList(any())).thenReturn(List.of(position));

        PortfolioAnalysisInput result = service.loadRequired(7L);

        assertEquals(new BigDecimal("5000"), result.monthlyBudget());
        assertEquals(new BigDecimal("0.15"), result.cashReserveRatio());
        assertEquals(1, result.positions().size());
        assertEquals("588200", result.positions().get(0).code());
    }

    @Test
    void shouldRejectMissingFinancialConfig() {
        when(configMapper.selectById(7L)).thenReturn(null);

        assertThrows(PortfolioDataMissingException.class, () -> service.loadRequired(7L));
    }

    @Test
    void shouldRejectEmptyPortfolioInsteadOfUsingExampleData() {
        UserConfig config = new UserConfig();
        config.setMonthlyBudget(5_000);
        when(configMapper.selectById(7L)).thenReturn(config);
        when(positionMapper.selectList(any())).thenReturn(List.of());

        assertThrows(PortfolioDataMissingException.class, () -> service.loadRequired(7L));
    }
}
