package com.bdlh.runtime.messaging;

import com.bdlh.runtime.messaging.OutboxDtos.SaveTaskRequest;
import com.bdlh.runtime.messaging.OutboxDtos.TaskSnapshot;
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
import java.util.List;

/** Java-owned persistence for the currently supported financial-task state machine. */
@Service
public class FinancialTaskStoreService {

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public FinancialTaskStoreService(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public TaskSnapshot create(String userId, SaveTaskRequest request) {
        validateRequest(request, false);
        TaskSnapshot existing = find(userId, request.taskId());
        if (existing != null) {
            return existing;
        }
        jdbcTemplate.update(
                "INSERT INTO runtime.financial_task(task_id, user_id, status, version, next_wakeup_at, expires_at, payload) "
                        + "VALUES (?, ?, ?, ?, ?, ?, ?::jsonb)",
                request.taskId(), userId, request.status(), request.version(), request.nextWakeupAt(),
                request.expiresAt(), writeJson(request.payload()));
        return required(userId, request.taskId());
    }

    @Transactional
    public TaskSnapshot update(String userId, SaveTaskRequest request) {
        validateRequest(request, true);
        int nextVersion = request.expectedVersion() + 1;
        int updated = jdbcTemplate.update(
                "UPDATE runtime.financial_task SET status = ?, version = ?, next_wakeup_at = ?, expires_at = ?, "
                        + "payload = ?::jsonb, updated_at = CURRENT_TIMESTAMP "
                        + "WHERE task_id = ? AND user_id = ? AND version = ?",
                request.status(), nextVersion, request.nextWakeupAt(), request.expiresAt(), writeJson(request.payload()),
                request.taskId(), userId, request.expectedVersion());
        if (updated != 1) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "TASK_VERSION_CONFLICT");
        }
        return required(userId, request.taskId());
    }

    public TaskSnapshot get(String userId, String taskId) {
        return required(userId, taskId);
    }

    public List<TaskSnapshot> list(String userId, int requestedLimit) {
        return jdbcTemplate.query(
                "SELECT task_id, status, version, next_wakeup_at, expires_at, payload FROM runtime.financial_task "
                        + "WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                this::map, userId, Math.min(Math.max(requestedLimit, 1), 100));
    }

    @Transactional
    public List<TaskSnapshot> claimDue(int requestedLimit, OffsetDateTime now) {
        int limit = Math.min(Math.max(requestedLimit, 1), 100);
        OffsetDateTime timestamp = now == null ? OffsetDateTime.now(ZoneOffset.UTC) : now;
        List<TaskSnapshot> rows = jdbcTemplate.query(
                "SELECT task_id, status, version, next_wakeup_at, expires_at, payload FROM runtime.financial_task "
                        + "WHERE status IN ('SCHEDULED', 'WAITING') AND next_wakeup_at <= ? AND expires_at > ? "
                        + "ORDER BY next_wakeup_at FOR UPDATE SKIP LOCKED LIMIT ?",
                this::map, timestamp, timestamp, limit);
        for (TaskSnapshot row : rows) {
            int nextVersion = row.version() + 1;
            jdbcTemplate.update(
                    "UPDATE runtime.financial_task SET status = 'RUNNING', version = ?, "
                            + "payload = jsonb_set(jsonb_set(payload, '{status}', '\"RUNNING\"'::jsonb, true), "
                            + "'{version}', to_jsonb(?::integer), true), updated_at = CURRENT_TIMESTAMP "
                            + "WHERE task_id = ? AND version = ?",
                    nextVersion, nextVersion, row.taskId(), row.version());
        }
        return rows.stream().map(row -> new TaskSnapshot(
                row.taskId(), "RUNNING", row.version() + 1, row.nextWakeupAt(), row.expiresAt(),
                updatePayload(row.payload(), "RUNNING", row.version() + 1))).toList();
    }

    @Transactional
    public int expireDue(OffsetDateTime now) {
        OffsetDateTime timestamp = now == null ? OffsetDateTime.now(ZoneOffset.UTC) : now;
        return jdbcTemplate.update(
                "UPDATE runtime.financial_task SET status = 'EXPIRED', version = version + 1, "
                        + "payload = jsonb_set(jsonb_set(payload, '{status}', '\"EXPIRED\"'::jsonb, true), "
                        + "'{version}', to_jsonb(version + 1), true), "
                        + "updated_at = CURRENT_TIMESTAMP WHERE status IN ('SCHEDULED', 'WAITING') AND expires_at <= ?",
                timestamp);
    }

    @Transactional
    public int recoverStale(OffsetDateTime now, OffsetDateTime staleBefore) {
        OffsetDateTime timestamp = now == null ? OffsetDateTime.now(ZoneOffset.UTC) : now;
        OffsetDateTime cutoff = staleBefore == null ? timestamp.minusMinutes(5) : staleBefore;
        return jdbcTemplate.update(
                "UPDATE runtime.financial_task SET status = 'WAITING', version = version + 1, next_wakeup_at = ?, "
                        + "payload = jsonb_set(jsonb_set(payload, '{status}', '\"WAITING\"'::jsonb, true), "
                        + "'{version}', to_jsonb(version + 1), true), updated_at = CURRENT_TIMESTAMP "
                        + "WHERE status = 'RUNNING' AND updated_at <= ?",
                timestamp, cutoff);
    }

    private TaskSnapshot required(String userId, String taskId) {
        TaskSnapshot result = find(userId, taskId);
        if (result == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "task not found or not accessible");
        }
        return result;
    }

    private TaskSnapshot find(String userId, String taskId) {
        List<TaskSnapshot> rows = jdbcTemplate.query(
                "SELECT task_id, status, version, next_wakeup_at, expires_at, payload FROM runtime.financial_task "
                        + "WHERE task_id = ? AND user_id = ?",
                this::map, taskId, userId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private TaskSnapshot map(ResultSet rs, int rowNum) throws SQLException {
        return new TaskSnapshot(rs.getString("task_id"), rs.getString("status"), rs.getInt("version"),
                rs.getObject("next_wakeup_at", OffsetDateTime.class), rs.getObject("expires_at", OffsetDateTime.class),
                readJson(rs.getString("payload")));
    }

    private void validateRequest(SaveTaskRequest request, boolean requireExpectedVersion) {
        if (request == null || blank(request.taskId()) || blank(request.status()) || request.version() == null
                || request.version() < 0 || request.nextWakeupAt() == null || request.expiresAt() == null
                || request.payload() == null || request.payload().isNull()
                || (requireExpectedVersion && (request.expectedVersion() == null || request.expectedVersion() < 0))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid task snapshot");
        }
    }

    private JsonNode updatePayload(JsonNode payload, String status, int version) {
        var copy = payload.deepCopy();
        if (copy.isObject()) {
            ((com.fasterxml.jackson.databind.node.ObjectNode) copy).put("status", status).put("version", version);
        }
        return copy;
    }

    private String writeJson(JsonNode value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "task payload cannot be serialized");
        }
    }

    private JsonNode readJson(String value) {
        try {
            return objectMapper.readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored task payload is invalid", exception);
        }
    }

    private static boolean blank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
