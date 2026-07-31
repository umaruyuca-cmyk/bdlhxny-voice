package com.stockwise.agent.routing;

import org.springframework.stereotype.Component;

/**
 * 作为付费模型唯一业务门禁，要求 Route、Skill Observation 和外部证据同时满足策略。
 */
@Component
public class PaidModelGate {

    private final RouteExecutionPolicyRegistry policyRegistry;

    public PaidModelGate(RouteExecutionPolicyRegistry policyRegistry) {
        this.policyRegistry = policyRegistry;
    }

    /**
     * 判断一次显式执行是否允许调用付费模型。
     */
    public PaidModelPermit evaluate(RouteDecision decision,
                                    SkillObservation observation,
                                    EvidenceBundle evidenceBundle) {
        RouteExecutionPolicy policy = policyRegistry.get(decision.route());
        if (policy.modelPolicy() != ModelPolicy.PAID_AFTER_VALIDATED_SKILL) {
            return new PaidModelPermit(false, "ROUTE_NOT_PAID");
        }
        if (observation == null || !observation.success()) {
            return new PaidModelPermit(false, "SKILL_NOT_SUCCESSFUL");
        }
        if (!observation.contractValidated()) {
            return new PaidModelPermit(false, "SKILL_CONTRACT_INVALID");
        }
        if (!observation.commandMatchesRoute()) {
            return new PaidModelPermit(false, "SKILL_COMMAND_MISMATCH");
        }
        if (!observation.subjectMatches()) {
            return new PaidModelPermit(false, "SKILL_SUBJECT_MISMATCH");
        }
        if (!observation.freshnessValidated()) {
            return new PaidModelPermit(false, "SKILL_DATA_STALE");
        }
        if (policy.webSearchRequired()
                && (evidenceBundle == null || !evidenceBundle.searchAttempted() || !evidenceBundle.sufficient())) {
            return new PaidModelPermit(false, "EXTERNAL_EVIDENCE_INSUFFICIENT");
        }
        return new PaidModelPermit(true, "ALLOWED");
    }
}
