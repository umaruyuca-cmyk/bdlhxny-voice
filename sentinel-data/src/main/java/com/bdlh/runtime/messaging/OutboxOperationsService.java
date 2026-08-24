package com.bdlh.runtime.messaging;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.UUID;

/** Read-only backlog data and explicit human compensation for the P4 Outbox. */
@Service
public class OutboxOperationsService {

    private final JdbcTemplate jdbcTemplate;

    public OutboxOperationsService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public OutboxStatus status() {
        return jdbcTemplate.queryForObject(
                "SELECT count(*) FILTER (WHERE status = 'PENDING') AS pending, "
                        + "count(*) FILTER (WHERE status = 'PUBLISHING') AS publishing, "
                        + "count(*) FILTER (WHERE status = 'FAILED') AS failed, "
                        + "EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - min(created_at) FILTER "
                        + "(WHERE status IN ('PENDING', 'PUBLISHING')))) AS oldest_seconds "
                        + "FROM runtime.outbox_event",
                (rs, rowNum) -> new OutboxStatus(
                        rs.getLong("pending"), rs.getLong("publishing"), rs.getLong("failed"),
                        rs.getObject("oldest_seconds") == null ? null : rs.getDouble("oldest_seconds")));
    }

    @Transactional
    public boolean requeueFailed(UUID eventId) {
        return jdbcTemplate.update(
                "UPDATE runtime.outbox_event SET status = 'PENDING', attempts = 0, next_attempt_at = ?, "
                        + "claim_token = NULL, claimed_at = NULL, last_error = 'MANUAL_REQUEUE', "
                        + "compensation_required = FALSE, updated_at = CURRENT_TIMESTAMP "
                        + "WHERE event_id = ? AND status = 'FAILED'",
                OffsetDateTime.now(ZoneOffset.UTC), eventId) == 1;
    }

    public record OutboxStatus(long pending, long publishing, long failed, Double oldestPendingSeconds) {
    }
}
