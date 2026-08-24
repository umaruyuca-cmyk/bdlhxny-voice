package com.bdlh.runtime.messaging;

import com.bdlh.runtime.messaging.OutboxDtos.CompleteTaskNotificationRequest;
import com.bdlh.runtime.messaging.OutboxDtos.CompletionResult;
import com.bdlh.runtime.messaging.OutboxDtos.OutboxEvent;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Owns the transactional boundary between a completed task and its notification command.
 * Publishing is deliberately absent here: P4 will relay claimed records to RocketMQ.
 */
@Service
public class TaskOutboxService {

    public static final String NOTIFICATION_TOPIC = "bdlh.notification.commands";
    public static final String NOTIFICATION_EVENT_TYPE = "NOTIFICATION_REQUESTED";
    private static final int MAX_ATTEMPTS = 8;

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public TaskOutboxService(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public CompletionResult completeTaskAndEnqueueNotification(
            String userId,
            String taskId,
            CompleteTaskNotificationRequest request) {
        String owner = required(userId, "user_id");
        String task = required(taskId, "task_id");
        if (request == null || request.expectedVersion() == null || request.expectedVersion() < 0) {
            throw badRequest("expected_version is required");
        }
        if (request == null || request.eventId() == null) {
            throw badRequest("event_id is required");
        }
        String idempotencyKey = required(request.idempotencyKey(), "idempotency_key");
        if (request.notificationPayload() == null || request.notificationPayload().isNull()) {
            throw badRequest("notification_payload is required");
        }

        ExistingOutbox existing = findByIdempotencyKey(idempotencyKey);
        if (existing != null) {
            ensureSameAggregate(existing, task, owner);
            return new CompletionResult(existing.eventId(), existing.status(), true);
        }

        TaskRow taskRow = lockTask(owner, task);
        if (taskRow == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found or not accessible");
        }
        // A competing retry may have selected the idempotency key before the first
        // transaction committed and then waited on this task row.  Re-read after
        // acquiring the lock so that retry remains idempotent rather than a conflict.
        existing = findByIdempotencyKey(idempotencyKey);
        if (existing != null) {
            ensureSameAggregate(existing, task, owner);
            return new CompletionResult(existing.eventId(), existing.status(), true);
        }
        if (taskRow.version() != request.expectedVersion()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "TASK_VERSION_CONFLICT");
        }
        if (!"TRIGGERED".equals(taskRow.status())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "TASK_NOT_TRIGGERED");
        }

        int aggregateVersion = taskRow.version() + 1;
        String completedPayload = request.completedTaskPayload() == null || request.completedTaskPayload().isNull()
                ? "payload"
                : "jsonb_set(jsonb_set(?::jsonb, '{status}', '\"COMPLETED\"'::jsonb, true), "
                        + "'{version}', to_jsonb(?::integer), true)";
        String updateSql = "UPDATE runtime.financial_task SET status = 'COMPLETED', version = ?, "
                + "payload = " + completedPayload + ", "
                + "notification_event_id = ?, updated_at = CURRENT_TIMESTAMP "
                + "WHERE task_id = ? AND user_id = ? AND version = ?";
        int completed = jdbcTemplate.update(
                request.completedTaskPayload() == null || request.completedTaskPayload().isNull()
                        ? updateSql
                        : updateSql,
                request.completedTaskPayload() == null || request.completedTaskPayload().isNull()
                        ? new Object[] {aggregateVersion, request.eventId(), task, owner, taskRow.version()}
                        : new Object[] {aggregateVersion, writeJson(request.completedTaskPayload()), aggregateVersion,
                                request.eventId(), task, owner, taskRow.version()});
        if (completed != 1) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "TASK_VERSION_CONFLICT");
        }
        jdbcTemplate.update(
                "INSERT INTO runtime.outbox_event(event_id, topic, event_type, schema_version, "
                        + "aggregate_type, aggregate_id, aggregate_version, idempotency_key, "
                        + "authenticated_user_id, payload, trace_id, correlation_id) "
                        + "VALUES (?, ?, ?, 1, 'FINANCIAL_TASK', ?, ?, ?, ?, ?::jsonb, ?, ?)",
                request.eventId(), NOTIFICATION_TOPIC, NOTIFICATION_EVENT_TYPE, task, aggregateVersion,
                idempotencyKey, owner, writeJson(request.notificationPayload()), nullable(request.traceId()),
                nullable(request.correlationId()));
        return new CompletionResult(request.eventId(), "PENDING", false);
    }

    /** Claim ready events safely for one relay instance.  A P4 publisher owns acknowledgement. */
    @Transactional
    public List<OutboxEvent> claimReadyEvents(int requestedLimit, OffsetDateTime now, OffsetDateTime staleBefore) {
        int limit = Math.min(Math.max(requestedLimit, 1), 100);
        OffsetDateTime timestamp = now == null ? OffsetDateTime.now(ZoneOffset.UTC) : now;
        OffsetDateTime stale = staleBefore == null ? timestamp.minusMinutes(5) : staleBefore;
        jdbcTemplate.update(
                "UPDATE runtime.outbox_event SET status = CASE WHEN attempts >= max_attempts THEN 'FAILED' ELSE 'PENDING' END, "
                        + "claim_token = NULL, claimed_at = NULL, next_attempt_at = ?, "
                        + "last_error = 'STALE_PUBLISHING_RECOVERED', compensation_required = (attempts >= max_attempts), "
                        + "updated_at = CURRENT_TIMESTAMP WHERE status = 'PUBLISHING' AND claimed_at <= ?",
                timestamp, stale);
        List<OutboxEvent> events = new ArrayList<>();
        List<OutboxRow> rows = jdbcTemplate.query(
                "SELECT event_id, topic, event_type, schema_version, aggregate_type, aggregate_id, "
                        + "aggregate_version, authenticated_user_id, payload, trace_id, correlation_id, attempts, created_at "
                        + "FROM runtime.outbox_event WHERE status = 'PENDING' AND attempts < max_attempts "
                        + "AND next_attempt_at <= ? "
                        + "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT ?",
                this::mapOutboxRow, timestamp, limit);
        for (OutboxRow row : rows) {
            UUID claimToken = UUID.randomUUID();
            int claimed = jdbcTemplate.update(
                    "UPDATE runtime.outbox_event SET status = 'PUBLISHING', attempts = attempts + 1, "
                            + "claim_token = ?, claimed_at = ?, updated_at = CURRENT_TIMESTAMP "
                            + "WHERE event_id = ? AND status = 'PENDING'",
                    claimToken, timestamp, row.eventId());
            if (claimed == 1) {
                events.add(row.asClaimed(claimToken));
            }
        }
        return events;
    }

    @Transactional
    public boolean markPublished(UUID eventId, UUID claimToken, OffsetDateTime publishedAt) {
        return jdbcTemplate.update(
                "UPDATE runtime.outbox_event SET status = 'PUBLISHED', published_at = ?, claim_token = NULL, "
                        + "claimed_at = NULL, last_error = NULL, updated_at = CURRENT_TIMESTAMP "
                        + "WHERE event_id = ? AND claim_token = ? AND status = 'PUBLISHING'",
                publishedAt == null ? OffsetDateTime.now(ZoneOffset.UTC) : publishedAt, eventId, claimToken) == 1;
    }

    @Transactional
    public boolean markPublishFailed(UUID eventId, UUID claimToken, String error, OffsetDateTime now) {
        OffsetDateTime timestamp = now == null ? OffsetDateTime.now(ZoneOffset.UTC) : now;
        int changed = jdbcTemplate.update(
                "UPDATE runtime.outbox_event SET status = CASE WHEN attempts >= max_attempts THEN 'FAILED' ELSE 'PENDING' END, "
                        + "next_attempt_at = CASE WHEN attempts >= max_attempts THEN next_attempt_at "
                        + "ELSE ? + (LEAST(attempts, 6) * INTERVAL '10 seconds') END, "
                        + "claim_token = NULL, claimed_at = NULL, last_error = ?, "
                        + "compensation_required = (attempts >= max_attempts), updated_at = CURRENT_TIMESTAMP "
                        + "WHERE event_id = ? AND claim_token = ? AND status = 'PUBLISHING'",
                timestamp, truncate(error), eventId, claimToken);
        return changed == 1;
    }

    private TaskRow lockTask(String userId, String taskId) {
        List<TaskRow> rows = jdbcTemplate.query(
                "SELECT status, version FROM runtime.financial_task WHERE task_id = ? AND user_id = ? FOR UPDATE",
                (rs, rowNum) -> new TaskRow(rs.getString("status"), rs.getInt("version")), taskId, userId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private ExistingOutbox findByIdempotencyKey(String idempotencyKey) {
        List<ExistingOutbox> rows = jdbcTemplate.query(
                "SELECT event_id, aggregate_id, authenticated_user_id, status FROM runtime.outbox_event "
                        + "WHERE idempotency_key = ?",
                (rs, rowNum) -> new ExistingOutbox(
                        rs.getObject("event_id", UUID.class), rs.getString("aggregate_id"),
                        rs.getString("authenticated_user_id"), rs.getString("status")),
                idempotencyKey);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private OutboxRow mapOutboxRow(ResultSet rs, int rowNum) throws SQLException {
        return new OutboxRow(
                rs.getObject("event_id", UUID.class), rs.getString("topic"), rs.getString("event_type"),
                rs.getInt("schema_version"), rs.getString("aggregate_type"), rs.getString("aggregate_id"),
                rs.getInt("aggregate_version"), rs.getString("authenticated_user_id"),
                readJson(rs.getString("payload")), rs.getString("trace_id"), rs.getString("correlation_id"),
                rs.getInt("attempts"), rs.getObject("created_at", OffsetDateTime.class));
    }

    private void ensureSameAggregate(ExistingOutbox event, String taskId, String userId) {
        if (!taskId.equals(event.aggregateId()) || !userId.equals(event.userId())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "IDEMPOTENCY_KEY_REUSED");
        }
    }

    private String writeJson(JsonNode value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw badRequest("notification_payload cannot be serialized");
        }
    }

    private JsonNode readJson(String value) {
        try {
            return objectMapper.readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored outbox payload is invalid", exception);
        }
    }

    private static String required(String value, String field) {
        String normalized = nullable(value);
        if (normalized == null) {
            throw badRequest(field + " is required");
        }
        return normalized;
    }

    private static String nullable(String value) {
        if (value == null || value.trim().isEmpty()) {
            return null;
        }
        return value.trim();
    }

    private static String truncate(String value) {
        String normalized = nullable(value);
        return normalized == null ? "PUBLISH_FAILED" : normalized.substring(0, Math.min(normalized.length(), 1000));
    }

    private static ResponseStatusException badRequest(String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }

    private record TaskRow(String status, int version) {
    }

    private record ExistingOutbox(UUID eventId, String aggregateId, String userId, String status) {
    }

    private record OutboxRow(
            UUID eventId, String topic, String eventType, int schemaVersion, String aggregateType,
            String aggregateId, int aggregateVersion, String authenticatedUserId, JsonNode payload,
            String traceId, String correlationId, int attempts, OffsetDateTime createdAt) {
        OutboxEvent asClaimed(UUID claimToken) {
            return new OutboxEvent(eventId, topic, eventType, schemaVersion, aggregateType, aggregateId,
                    aggregateVersion, authenticatedUserId, payload, traceId, correlationId, attempts + 1,
                    claimToken, createdAt);
        }
    }
}
