package com.bdlh.runtime.runtime;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.OffsetDateTime;
import java.util.List;

/** 用例级 Runtime Data API 的输入和输出，不暴露数据库实体。 */
public final class RuntimeDataDtos {

    private RuntimeDataDtos() {
    }

    public record EnsureSessionRequest(String requestedSessionId) {
    }

    public record ChatMessageRequest(String role, String content) {
    }

    public record PendingRunRequest(
            String runId,
            String threadId,
            String checkpointId,
            String runtimePath,
            String pauseReason,
            Boolean awaitingRouteConfirm) {
    }

    public record ChatMessageResponse(String role, String content, OffsetDateTime createdAt) {
    }

    public record ChatSessionResponse(
            String sessionId,
            String title,
            List<ChatMessageResponse> messages,
            String pendingRunId,
            String pendingThreadId,
            String pendingCheckpointId,
            String pendingRuntimePath,
            String pauseReason,
            Boolean awaitingRouteConfirm,
            OffsetDateTime updatedAt) {
    }

    public record UpsertRunRequest(String threadId, String checkpointId, String runtimePath) {
    }

    public record RunLocationResponse(
            String runId,
            String threadId,
            String checkpointId,
            String runtimePath,
            OffsetDateTime updatedAt) {
    }

    public record RunEventRequest(String eventType, JsonNode payload) {
    }

    public record SaveRunProjectionRequest(
            String threadId,
            String status,
            String nextStage,
            JsonNode finalResponse,
            JsonNode interrupts,
            List<RunEventRequest> events) {
    }

    public record RunEventResponse(
            int sequenceNo,
            String eventType,
            JsonNode payload,
            OffsetDateTime createdAt) {
    }

    public record RunProjectionResponse(
            String runId,
            String threadId,
            String status,
            String nextStage,
            JsonNode finalResponse,
            JsonNode interrupts,
            List<RunEventResponse> events,
            OffsetDateTime updatedAt) {
    }

    public record SaveHistoryRequest(
            String threadId,
            String runId,
            String status,
            JsonNode payload,
            OffsetDateTime createdAt) {
    }

    public record AnalysisHistoryResponse(
            String historyId,
            String threadId,
            String runId,
            String status,
            JsonNode payload,
            OffsetDateTime createdAt) {
    }
}
