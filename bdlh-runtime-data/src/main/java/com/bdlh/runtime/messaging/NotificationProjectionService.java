package com.bdlh.runtime.messaging;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/** Consumer-side notification projection; invoked in the Java Inbox transaction. */
@Service
public class NotificationProjectionService {

    public static final String CONSUMER_GROUP = "bdlh-notification-consumer";

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final ConsumerInboxService consumerInboxService;

    public NotificationProjectionService(
            JdbcTemplate jdbcTemplate,
            ObjectMapper objectMapper,
            ConsumerInboxService consumerInboxService) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.consumerInboxService = consumerInboxService;
    }

    public boolean project(UUID eventId, byte[] body) {
        JsonNode envelope;
        try {
            envelope = objectMapper.readTree(body);
        } catch (Exception exception) {
            throw new IllegalArgumentException("invalid RocketMQ notification envelope", exception);
        }
        if (!TaskOutboxService.NOTIFICATION_EVENT_TYPE.equals(requiredText(envelope, "event_type"))) {
            throw new IllegalArgumentException("unexpected notification event type");
        }
        JsonNode payload = envelope.path("payload");
        return consumerInboxService.processOnce(
                CONSUMER_GROUP,
                eventId,
                () -> jdbcTemplate.update(
                        "INSERT INTO runtime.user_notification(notification_id, event_id, user_id, task_id, channel, "
                                + "title, body, observed_price, currency, observation_time) "
                                + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (event_id) DO NOTHING",
                        eventId,
                        eventId,
                        requiredText(envelope, "authenticated_user_id"),
                        requiredText(payload, "task_id"),
                        optionalText(payload, "channel", "IN_APP"),
                        requiredText(payload, "title"),
                        requiredText(payload, "body"),
                        payload.path("observed_price").decimalValue(),
                        optionalText(payload, "currency", null),
                        optionalTimestamp(payload, "observation_time")),
                "notification persisted");
    }

    public List<NotificationView> listForUser(String userId, int requestedLimit) {
        return jdbcTemplate.query(
                "SELECT notification_id, task_id, channel, title, body, observed_price, currency, observation_time, created_at "
                        + "FROM runtime.user_notification WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (rs, rowNum) -> new NotificationView(
                        rs.getObject("notification_id", UUID.class), rs.getString("task_id"), rs.getString("channel"),
                        rs.getString("title"), rs.getString("body"), rs.getBigDecimal("observed_price"),
                        rs.getString("currency"), rs.getObject("observation_time", OffsetDateTime.class),
                        rs.getObject("created_at", OffsetDateTime.class)),
                userId, Math.min(Math.max(requestedLimit, 1), 100));
    }

    private static String requiredText(JsonNode node, String field) {
        String value = optionalText(node, field, null);
        if (value == null) {
            throw new IllegalArgumentException(field + " is required");
        }
        return value;
    }

    private static String optionalText(JsonNode node, String field, String fallback) {
        String value = node.path(field).asText("").trim();
        return value.isEmpty() ? fallback : value;
    }

    private static OffsetDateTime optionalTimestamp(JsonNode node, String field) {
        String value = optionalText(node, field, null);
        return value == null ? null : OffsetDateTime.parse(value);
    }

    public record NotificationView(
            UUID notificationId,
            String taskId,
            String channel,
            String title,
            String body,
            java.math.BigDecimal observedPrice,
            String currency,
            OffsetDateTime observationTime,
            OffsetDateTime createdAt) {
    }
}
