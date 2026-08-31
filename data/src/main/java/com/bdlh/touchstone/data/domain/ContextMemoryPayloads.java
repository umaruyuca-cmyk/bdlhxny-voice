package com.bdlh.touchstone.data.domain;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import java.util.List;
import java.util.UUID;

/** 上下文工作台内部接口的写入载荷。 */
public final class ContextMemoryPayloads {
    private ContextMemoryPayloads() {}

    public record SessionEventInput(
            @NotBlank String eventId,
            @NotBlank String turnId,
            @Min(1) int sequence,
            @NotBlank String eventType,
            @NotBlank String role,
            String content,
            String contentRef,
            @Min(0) int tokenCount,
            @NotBlank String occurredAt,
            String toolCallId,
            String parentEventId,
            @NotBlank String securityLevel,
            @NotBlank String contentHash) {}

    public record SaveSessionRequest(
            @NotNull UUID accountId,
            @NotBlank String sessionId,
            @NotBlank String title,
            @NotBlank String sourceType,
            String sourceRef,
            @NotBlank String sourceHash,
            @Min(1) long sourceVersion,
            @NotBlank String status,
            @NotEmpty List<@Valid SessionEventInput> events) {}

    public record CreateBuildRequest(
            @NotNull UUID accountId,
            @NotBlank String sessionId,
            @NotBlank String currentRequestEventId,
            @NotBlank String algorithmVersion,
            @NotBlank String idempotencyKey,
            @NotBlank String requestHash,
            JsonNode configSnapshot) {}

    public record UpdateBuildRequest(
            @NotNull UUID accountId,
            @NotBlank String status,
            @NotBlank String currentPhase,
            @NotNull JsonNode steps,
            @NotNull JsonNode budget,
            @NotNull JsonNode itemCounts,
            @NotNull JsonNode llmUsage,
            @NotNull JsonNode warnings,
            JsonNode decisions,
            String errorCode,
            String errorMessage,
            JsonNode agentRunSnapshot) {}

    public record SaveArtifactRequest(
            @NotNull UUID accountId,
            @NotNull JsonNode messages,
            @NotBlank String contentHash,
            @Min(0) int tokenCount,
            @NotBlank String tokenizerVersion,
            JsonNode memorySegments) {}

    public record SaveMemorySegmentRequest(
            @NotNull UUID accountId,
            @NotBlank String startEventId,
            @NotBlank String endEventId,
            @NotNull JsonNode sourceEventIds,
            @NotBlank String sourceHash,
            @Min(0) int sourceTokens,
            @NotBlank String summaryContent,
            @Min(0) int summaryTokens,
            @NotBlank String status,
            String summaryModel,
            @NotBlank String promptVersion,
            @NotBlank String algorithmVersion,
            @NotBlank String generationMode,
            String fallbackReason) {}
}
