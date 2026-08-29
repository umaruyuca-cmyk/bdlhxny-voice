package com.bdlh.touchstone.data.domain;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import java.util.List;
import java.util.UUID;

public final class RunPayloads {
    private RunPayloads() {}

    public record CreateBatchRequest(
            @NotBlank String name,
            @NotBlank String experimentType,
            @NotNull JsonNode fixedConditions) {}

    public record CreateRunRequest(
            UUID batchId,
            @NotBlank String caseId,
            @Min(1) int caseVersion,
            @NotBlank String variantId,
            @NotBlank String snapshotId,
            @NotBlank String agentMode,
            @NotBlank String contextStrategy,
            @NotBlank String model,
            @NotBlank String gitCommit,
            JsonNode modelConfig) {}

    public record CompleteBatchRequest(@NotBlank String status) {}

    /** 批次执行报告写入:报告为执行器完整 payload(JSON),完成时由 engine 落库。 */
    public record SaveBatchReportRequest(@NotNull JsonNode report) {}

    public record ContextItemInput(
            @NotBlank String itemKey,
            @NotBlank String itemType,
            @NotBlank String classification,
            @NotNull JsonNode content,
            String contentRef,
            String sourceId,
            String ownerId,
            String observedAt,
            String validFrom,
            String validTo,
            int priority,
            boolean trusted,
            @Min(0) int rawTokens,
            @NotBlank String contentHash,
            int sequence) {}

    public record ContextDecisionInput(
            @NotBlank String itemKey,
            @NotBlank String action,
            @NotBlank String reason,
            @Min(0) int inputTokens,
            @Min(0) int outputTokens,
            JsonNode outputContent,
            String outputHash,
            String referenceId,
            int decisionOrder) {}

    public record ContextMessageInput(
            @Min(0) int messageOrder,
            @NotBlank String role,
            @NotBlank String content,
            @NotBlank String contentHash,
            @Min(0) int tokens) {}

    public record SaveContextBuildRequest(
            @NotBlank String strategy,
            @NotBlank String tokenizerVersion,
            @NotBlank String compressionVersion,
            @Min(1) int tokenBudget,
            @Min(0) int originalTokens,
            @Min(0) int workingTokens,
            @Min(0) int compressionInputTokens,
            @Min(0) int compressionOutputTokens,
            @Min(0) long durationMs,
            boolean requiredRetained,
            boolean budgetFit,
            boolean referencesValid,
            boolean instructionIsolated,
            @NotBlank String status,
            String errorCode,
            @NotEmpty List<@Valid ContextItemInput> items,
            @NotEmpty List<@Valid ContextDecisionInput> decisions,
            @NotEmpty List<@Valid ContextMessageInput> messages) {}

    public record RunEventInput(
            @Min(0) int sequence,
            @NotBlank String eventType,
            @NotNull JsonNode payload,
            String occurredAt) {}

    public record SaveEventsRequest(@NotEmpty List<@Valid RunEventInput> events) {}

    public record SaveEvaluationRequest(
            @NotBlank String evaluatorVersion,
            boolean validRun,
            @NotBlank String status,
            @NotNull JsonNode checks,
            JsonNode metrics) {}

    public record CompleteRunRequest(
            @NotBlank String status,
            JsonNode output,
            String errorCategory,
            String errorMessage) {}

    /** 运行配置补全:提前建行后,运行完成回写完整 modelConfig。 */
    public record UpdateModelConfigRequest(@NotNull JsonNode modelConfig) {}

    public record LlmConfigRequest(
            @NotBlank String baseUrl,
            @NotBlank String model,
            String apiKey) {}

    public record ModelCallMessageInput(
            @Min(0) int messageOrder,
            @NotBlank String role,
            String content,
            String contentRef,
            @Min(0) int tokens,
            @NotBlank String contentHash) {}

    /**
     * 单次模型调用:计量行 + 应用层请求快照(可观测性设计 §4.3/§6.1)。
     * requestHash 覆盖 model+messages+toolSchemas+sentParams;快照 JSONB 字段
     * 均可空(旧版本 engine 不发送时保持兼容)。
     */
    public record ModelCallInput(
            @Min(0) int sequence,
            @NotBlank String purpose,
            @NotBlank String model,
            @NotBlank String requestHash,
            String responseHash,
            @Min(0) int inputTokens,
            @Min(0) int outputTokens,
            @Min(0) long durationMs,
            @Min(0) int retryCount,
            @NotBlank String status,
            String errorCategory,
            String decision,
            Integer requestSnapshotVersion,
            JsonNode requestPayload,
            JsonNode toolSchemas,
            JsonNode requestedParams,
            JsonNode sentParams,
            JsonNode unsupportedParams,
            JsonNode responseSummary,
            List<@Valid ModelCallMessageInput> messages) {}

    public record SaveModelCallsRequest(@NotEmpty List<@Valid ModelCallInput> calls) {}

    /**
     * 单次工具调用:含与发起模型调用、模型生成 call_id、全局事件序号的
     * 关联字段(可观测性设计 §4.4/§6.2);modelCallSequence 由数据服务解析为
     * tool_calls.model_call_id 外键。
     */
    public record ToolCallInput(
            @Min(0) int sequence,
            @NotBlank String toolName,
            @NotNull JsonNode arguments,
            @NotBlank String argumentsHash,
            @NotBlank String status,
            JsonNode resultSummary,
            String resultHash,
            String sourceTime,
            @Min(0) long durationMs,
            String auditCode,
            boolean fixtureHit,
            String errorCategory,
            String callId,
            Integer modelCallSequence,
            Integer requestedEventSequence,
            Integer completedEventSequence,
            String resultRef) {}

    public record SaveToolCallsRequest(@NotEmpty List<@Valid ToolCallInput> calls) {}

    /** 单次治理检查;toolCallSequence/modelCallSequence 解析为对应外键。 */
    public record GuardrailCheckInput(
            @Min(0) int sequence,
            @NotBlank String stage,
            @NotBlank String decision,
            String auditCode,
            JsonNode ruleIds,
            JsonNode reasons,
            String toolName,
            Integer toolCallSequence,
            Integer modelCallSequence,
            @Min(0) long durationMs,
            JsonNode detail) {}

    public record SaveGuardrailChecksRequest(@NotEmpty List<@Valid GuardrailCheckInput> checks) {}

    public record SaveMeasurementsRequest(
            @Min(0) long queueMs,
            @Min(0) long snapshotMs,
            @Min(0) long contextCollectMs,
            @Min(0) long contextCompressMs,
            @Min(0) long toolLoadingMs,
            @Min(0) long llmMs,
            @Min(0) long toolMs,
            @Min(0) long guardrailMs,
            @Min(0) long judgmentMs,
            Long firstOutputMs,
            @Min(0) long totalDurationMs,
            @Min(0) int promptTokens,
            @Min(0) int cachedPromptTokens,
            @Min(0) int completionTokens,
            @Min(0) int compressionInputTokens,
            @Min(0) int compressionOutputTokens) {}

    public record SaveArtifactRequest(
            @NotBlank String artifactType,
            @NotBlank String storageRef,
            @NotBlank String contentHash,
            boolean publicArtifact) {}

    public record PublicationRunInput(
            @NotBlank String runId,
            @NotBlank String publicStorageRef,
            @NotBlank String publicContentHash) {}

    public record RegisterPublicationRequest(
            @NotBlank String batchId,
            @NotBlank String title,
            @NotBlank String status,
            @NotBlank String fieldPolicyVersion,
            @NotBlank String indexStorageRef,
            @NotBlank String contentHash,
            @NotEmpty List<@Valid PublicationRunInput> runs) {}
}
