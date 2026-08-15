package com.bdlh.runtime.agent.routing;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证付费模型只在路由和确定性数据全部通过校验后放行。
 */
class PaidModelGateTest {

    private final PaidModelGate gate = new PaidModelGate(new RouteExecutionPolicyRegistry());

    @Test
    void marketFactCanNeverUsePaidModel() {
        PaidModelPermit permit = gate.evaluate(decision(RequestRoute.MARKET_FACT),
                validObservation(), EvidenceBundle.notRequired());

        assertFalse(permit.allowed());
    }

    @Test
    void causalAnalysisRequiresSufficientEvidence() {
        PaidModelPermit rejected = gate.evaluate(decision(RequestRoute.MARKET_CAUSAL_ANALYSIS),
                validObservation(), new EvidenceBundle(true, false, 1, 1, 0));
        PaidModelPermit allowed = gate.evaluate(decision(RequestRoute.MARKET_CAUSAL_ANALYSIS),
                validObservation(), new EvidenceBundle(true, true, 4, 3, 1));

        assertFalse(rejected.allowed());
        assertTrue(allowed.allowed());
    }

    private RouteDecision decision(RequestRoute route) {
        RouteExecutionPolicy policy = new RouteExecutionPolicyRegistry().get(route);
        return new RouteDecision(route, policy.compatibleIntent(), policy.modelPolicy(), "600519",
                "TEST", 1.0, true, policy.webSearchRequired(), false, null);
    }

    private SkillObservation validObservation() {
        return new SkillObservation(true, true, true, true, true);
    }
}
