package com.bdlh.runtime.messaging;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.OffsetDateTime;
import java.util.UUID;

/** Outbox and inbox use-case DTOs.  They are not database entities. */
public final class OutboxDtos {

    private OutboxDtos() {
    }

    public record CompleteTaskNotificationRequest(
            Integer expectedVersion,
            UUID eventId,
            String idempotencyKey,
            JsonNode notificationPayload,
            JsonNode completedTaskPayload,
            String traceId,
            String correlationId) {
    }

    public record TaskSnapshot(
            String taskId,
            String status,
            int version,
            OffsetDateTime nextWakeupAt,
            OffsetDateTime expiresAt,
            JsonNode payload) {
    }

    public record SaveTaskRequest(
            String taskId,
            String status,
            Integer version,
            Integer expectedVersion,
            OffsetDateTime nextWakeupAt,
            OffsetDateTime expiresAt,
            JsonNode payload) {
    }

    public record OutboxEvent(
            UUID eventId,
            String topic,
            String eventType,
            int schemaVersion,
            String aggregateType,
            String aggregateId,
            int aggregateVersion,
            String authenticatedUserId,
            JsonNode payload,
            String traceId,
            String correlationId,
            int attempts,
            UUID claimToken,
            OffsetDateTime createdAt) {
    }

    public record CompletionResult(UUID eventId, String status, boolean idempotent) {
    }
}
