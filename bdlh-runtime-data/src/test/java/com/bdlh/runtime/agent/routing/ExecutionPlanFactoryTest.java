package com.bdlh.runtime.agent.routing;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 验证因果分析和板块分析只能执行主体对应的本轮 Action。
 */
class ExecutionPlanFactoryTest {

    private final ExecutionPlanFactory factory = new ExecutionPlanFactory();

    @Test
    void stockCausalPlanUsesStockAndSearch() {
        ExecutionPlan plan = factory.create(decision(
                RequestRoute.MARKET_CAUSAL_ANALYSIS,
                RouteSubjectType.STOCK,
                List.of("600519"),
                List.of(),
                SectorType.UNKNOWN));

        assertThat(plan.actions()).containsExactly("stock", "webSearch");
    }

    @Test
    void sectorCausalPlanUsesSectorAndSearch() {
        ExecutionPlan plan = factory.create(decision(
                RequestRoute.MARKET_CAUSAL_ANALYSIS,
                RouteSubjectType.SECTOR,
                List.of(),
                List.of("银行"),
                SectorType.INDUSTRY));

        assertThat(plan.actions()).containsExactly("sector", "webSearch");
    }

    @Test
    void quantAndSectorPlansCannotCrossCommands() {
        ExecutionPlan quant = factory.create(decision(
                RequestRoute.QUANT_DECISION,
                RouteSubjectType.ETF_POOL,
                List.of("510300", "159915"),
                List.of(),
                SectorType.UNKNOWN));
        ExecutionPlan sector = factory.create(decision(
                RequestRoute.SECTOR_ANALYSIS,
                RouteSubjectType.SECTOR,
                List.of(),
                List.of("新能源车"),
                SectorType.CONCEPT));

        assertThat(quant.actions()).containsExactly("quant");
        assertThat(sector.actions()).containsExactly("sector");
    }

    private RouteDecision decision(RequestRoute route,
                                   RouteSubjectType subjectType,
                                   List<String> symbols,
                                   List<String> sectors,
                                   SectorType sectorType) {
        RouteExecutionPolicy policy = new RouteExecutionPolicyRegistry().get(route);
        return new RouteDecision(
                route,
                policy.compatibleIntent(),
                policy.modelPolicy(),
                subjectType,
                symbols,
                sectors,
                sectorType,
                "TEST",
                RouteSource.REGEX,
                1.0,
                !policy.allowedSkillCommands().isEmpty(),
                policy.webSearchRequired(),
                false,
                null);
    }
}
