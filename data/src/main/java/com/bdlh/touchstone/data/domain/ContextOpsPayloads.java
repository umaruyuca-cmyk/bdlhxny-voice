package com.bdlh.touchstone.data.domain;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.util.List;
import java.util.UUID;

/** 上下文细粒度 RBAC(授权/审计/跨所有者运维视图)与 P2 定时分析的内部载荷。 */
public final class ContextOpsPayloads {
    private ContextOpsPayloads() {}

    public record CreateGrantRequest(
            @NotNull UUID ownerAccountId,
            @NotNull UUID granteeAccountId,
            @NotBlank String scope,
            String buildId) {}

    public record WriteAuditRequest(
            UUID accountId,
            @NotBlank String action,
            boolean succeeded,
            JsonNode detail) {}

    /** 摘要段语义质量抽检结果(verdict=ERROR 表示评审调用失败,不伪造通过)。 */
    public record SaveQualityCheckRequest(
            @NotNull UUID accountId,
            @NotBlank String segmentId,
            @NotBlank String sessionId,
            @NotBlank String verdict,
            List<String> missingFacts,
            List<String> hallucinations,
            String judgeModel,
            @NotBlank String promptVersion,
            @NotBlank String sourceHashAtCheck,
            String errorCode,
            JsonNode detail) {}

    public record StartAnalysisRunRequest(@NotBlank String triggerSource) {}

    public record FinishAnalysisRunRequest(
            @NotBlank String status,
            Integer sampledSegments,
            Integer judgeCalls,
            Integer judgeErrors,
            JsonNode report,
            String errorCode) {}
}
