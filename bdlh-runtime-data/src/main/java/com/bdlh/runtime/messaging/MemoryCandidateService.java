package com.bdlh.runtime.messaging;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.UUID;

/** Java-owned Outbox entry point for governed L3 memory candidates. */
@Service
public class MemoryCandidateService {

    public static final String TOPIC = "bdlh.memory.commands";
    public static final String EVENT_TYPE = "MEMORY_CANDIDATE_CREATED";
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public MemoryCandidateService(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public UUID enqueue(String userId, MemoryCandidateRequest request) {
        if (request == null || request.candidateId() == null || blank(request.content())
                || request.content().length() > 1200 || request.metadata() == null || request.metadata().isNull()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid memory candidate");
        }
        if (!"confirmed".equals(request.metadata().path("knowledge_type").asText())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "memory candidate must be confirmed");
        }
        UUID eventId = request.candidateId();
        String idempotencyKey = "memory-candidate:" + eventId;
        int inserted = jdbcTemplate.update(
                "INSERT INTO runtime.outbox_event(event_id, topic, event_type, schema_version, aggregate_type, "
                        + "aggregate_id, aggregate_version, idempotency_key, authenticated_user_id, payload, "
                        + "trace_id, correlation_id) VALUES (?, ?, ?, 1, 'MEMORY_CANDIDATE', ?, 1, ?, ?, ?::jsonb, ?, ?) "
                        + "ON CONFLICT (idempotency_key) DO NOTHING",
                eventId, TOPIC, EVENT_TYPE, eventId.toString(), idempotencyKey, userId,
                writePayload(userId, request), nullable(request.traceId()), nullable(request.correlationId()));
        if (inserted == 0) {
            return eventId;
        }
        return eventId;
    }

    private String writePayload(String userId, MemoryCandidateRequest request) {
        try {
            var payload = objectMapper.createObjectNode();
            payload.put("candidate_id", request.candidateId().toString());
            payload.put("user_id", userId);
            payload.put("content", request.content().trim());
            payload.set("metadata", request.metadata());
            payload.put("created_at", OffsetDateTime.now(ZoneOffset.UTC).toString());
            return objectMapper.writeValueAsString(payload);
        } catch (Exception exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "memory candidate cannot be serialized");
        }
    }

    private static boolean blank(String value) {
        return value == null || value.trim().isEmpty();
    }

    private static String nullable(String value) {
        return blank(value) ? null : value.trim();
    }

    public record MemoryCandidateRequest(
            UUID candidateId,
            String content,
            JsonNode metadata,
            String traceId,
            String correlationId) {
    }
}
