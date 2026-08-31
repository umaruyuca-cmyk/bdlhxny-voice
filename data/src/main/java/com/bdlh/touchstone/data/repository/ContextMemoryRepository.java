package com.bdlh.touchstone.data.repository;

import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.CreateBuildRequest;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.SaveArtifactRequest;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.SaveMemorySegmentRequest;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.SaveSessionRequest;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.SessionEventInput;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.UpdateBuildRequest;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

/** 生产会话、增量摘要和独立上下文构建的 PostgreSQL 访问层。 */
@Repository
public class ContextMemoryRepository {
    public record BuildCreation(UUID buildId, boolean replay) {}

    public static final class BuildConflict extends RuntimeException {
        private final String code;
        private final UUID activeBuildId;

        public BuildConflict(String code, UUID activeBuildId) {
            super(code);
            this.code = code;
            this.activeBuildId = activeBuildId;
        }

        public String code() {
            return code;
        }

        public UUID activeBuildId() {
            return activeBuildId;
        }
    }

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public ContextMemoryRepository(JdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    public List<Map<String, Object>> listSessions(UUID accountId) {
        return jdbc.query(
                """
                SELECT s.id, s.title, s.source_type, s.source_ref, s.source_hash,
                       s.source_version, s.status, s.created_at, s.updated_at,
                       count(e.event_id) AS event_count,
                       count(DISTINCT e.turn_id) AS turn_count,
                       count(*) FILTER (WHERE e.event_type = 'user_message') AS user_message_count,
                       (SELECT se.event_id FROM touchstone.session_events se
                        WHERE se.session_id = s.id AND se.event_type = 'user_message'
                        ORDER BY se.sequence DESC LIMIT 1) AS default_current_request_event_id
                FROM touchstone.context_sessions s
                LEFT JOIN touchstone.session_events e ON e.session_id = s.id
                WHERE s.account_id = ?
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.id
                """,
                this::mapSessionSummary,
                accountId);
    }

    public Optional<Map<String, Object>> findSession(UUID accountId, String sessionId) {
        List<Map<String, Object>> rows = jdbc.query(
                """
                SELECT id, title, source_type, source_ref, source_hash, source_version,
                       status, created_at, updated_at
                FROM touchstone.context_sessions
                WHERE account_id = ? AND id = ?
                """,
                (rs, rowNumber) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("sessionId", rs.getString("id"));
                    row.put("title", rs.getString("title"));
                    row.put("sourceType", rs.getString("source_type"));
                    row.put("sourceRef", rs.getString("source_ref"));
                    row.put("sourceHash", rs.getString("source_hash"));
                    row.put("sourceVersion", rs.getLong("source_version"));
                    row.put("status", rs.getString("status"));
                    row.put("createdAt", rs.getObject("created_at"));
                    row.put("updatedAt", rs.getObject("updated_at"));
                    return row;
                },
                accountId,
                sessionId);
        if (rows.isEmpty()) {
            return Optional.empty();
        }
        Map<String, Object> session = rows.get(0);
        session.put("events", listEvents(accountId, sessionId));
        return Optional.of(session);
    }

    public List<Map<String, Object>> listEvents(UUID accountId, String sessionId) {
        return jdbc.query(
                """
                SELECT e.event_id, e.turn_id, e.sequence, e.event_type, e.role,
                       e.content, e.content_ref, e.token_count, e.occurred_at,
                       e.tool_call_id, e.parent_event_id, e.security_level, e.content_hash
                FROM touchstone.session_events e
                JOIN touchstone.context_sessions s ON s.id = e.session_id
                WHERE e.session_id = ? AND s.account_id = ?
                ORDER BY e.sequence
                """,
                this::mapEvent,
                sessionId,
                accountId);
    }

    @Transactional
    public void saveSession(SaveSessionRequest request) {
        int sessionRows = jdbc.update(
                """
                INSERT INTO touchstone.context_sessions
                    (id, account_id, title, source_type, source_ref, source_hash,
                     source_version, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    source_ref = EXCLUDED.source_ref,
                    source_hash = EXCLUDED.source_hash,
                    source_version = EXCLUDED.source_version,
                    status = EXCLUDED.status,
                    updated_at = now()
                WHERE touchstone.context_sessions.account_id = EXCLUDED.account_id
                """,
                request.sessionId(),
                request.accountId(),
                request.title(),
                request.sourceType(),
                request.sourceRef(),
                request.sourceHash(),
                request.sourceVersion(),
                request.status());
        if (sessionRows != 1) {
            throw new IllegalArgumentException("SESSION_OWNER_MISMATCH");
        }
        for (SessionEventInput event : request.events()) {
            jdbc.update(
                    """
                    INSERT INTO touchstone.session_events
                        (session_id, event_id, account_id, turn_id, sequence,
                         event_type, role, content, content_ref, token_count,
                         occurred_at, tool_call_id, parent_event_id, security_level,
                         content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::timestamptz, ?, ?, ?, ?)
                    ON CONFLICT (session_id, event_id) DO NOTHING
                    """,
                    request.sessionId(),
                    event.eventId(),
                    request.accountId(),
                    event.turnId(),
                    event.sequence(),
                    event.eventType(),
                    event.role(),
                    event.content(),
                    event.contentRef(),
                    event.tokenCount(),
                    event.occurredAt(),
                    event.toolCallId(),
                    event.parentEventId(),
                    event.securityLevel(),
                    event.contentHash());
        }
    }

    @Transactional
    public BuildCreation createBuild(CreateBuildRequest request) {
        // 唯一索引负责最终兜底；事务级 advisory lock 让“查幂等/查活跃/创建”成为
        // 单个 account 范围内可读的原子流程，并能稳定返回已有 build id。
        List<String> lockKeys = List.of(
                        "context-build:idem:" + request.accountId() + ":" + request.idempotencyKey(),
                        "context-build:session:" + request.accountId() + ":" + request.sessionId())
                .stream()
                .sorted()
                .toList();
        for (String lockKey : lockKeys) {
            jdbc.queryForList(
                    "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
                    lockKey);
        }
        List<Map<String, Object>> idempotent = jdbc.queryForList(
                """
                SELECT id, request_hash FROM touchstone.context_builds
                WHERE account_id = ? AND idempotency_key = ?
                """,
                request.accountId(),
                request.idempotencyKey());
        if (!idempotent.isEmpty()) {
            Map<String, Object> existing = idempotent.get(0);
            UUID buildId = (UUID) existing.get("id");
            if (!request.requestHash().equals(String.valueOf(existing.get("request_hash")))) {
                throw new BuildConflict("IDEMPOTENCY_KEY_REUSED", buildId);
            }
            return new BuildCreation(buildId, true);
        }
        List<UUID> active = jdbc.query(
                """
                SELECT id FROM touchstone.context_builds
                WHERE account_id = ? AND session_id = ? AND status IN ('PENDING', 'RUNNING')
                ORDER BY created_at DESC LIMIT 1
                """,
                (rs, rowNumber) -> rs.getObject("id", UUID.class),
                request.accountId(),
                request.sessionId());
        if (!active.isEmpty()) {
            throw new BuildConflict("ACTIVE_BUILD_EXISTS", active.get(0));
        }
        UUID buildId = UUID.randomUUID();
        int inserted = jdbc.update(
                """
                INSERT INTO touchstone.context_builds
                    (id, run_id, strategy, tokenizer_version, compression_version,
                     token_budget, original_tokens, working_tokens,
                     compression_input_tokens, compression_output_tokens, duration_ms,
                     required_retained, budget_fit, references_valid, instruction_isolated,
                     status, session_id, account_id, current_request_event_id,
                     algorithm_version, config_snapshot, source_version, current_phase,
                     step_snapshot, budget_snapshot, item_counts, llm_usage, warnings,
                     idempotency_key, request_hash, updated_at)
                SELECT ?, NULL, ?, 'pending', ?, 1, 0, 0, 0, 0, 0,
                       false, false, false, true, 'PENDING', s.id, s.account_id, ?,
                       ?, ?::jsonb, s.source_version, 'LOAD_HISTORY', '[]'::jsonb,
                       '{}'::jsonb, '{}'::jsonb,
                       '{"classification_calls":0,"summary_calls":0,"cache_hits":0}'::jsonb,
                       '[]'::jsonb, ?, ?, now()
                FROM touchstone.context_sessions s
                WHERE s.id = ? AND s.account_id = ?
                """,
                buildId,
                request.algorithmVersion(),
                request.algorithmVersion(),
                request.currentRequestEventId(),
                request.algorithmVersion(),
                json(request.configSnapshot()),
                request.idempotencyKey(),
                request.requestHash(),
                request.sessionId(),
                request.accountId());
        if (inserted != 1) {
            throw new IllegalArgumentException("CONTEXT_SESSION_NOT_FOUND");
        }
        return new BuildCreation(buildId, false);
    }

    @Transactional
    public void updateBuild(UUID buildId, UpdateBuildRequest request) {
        int updated = jdbc.update(
                """
                UPDATE touchstone.context_builds SET
                    status = ?, current_phase = ?, step_snapshot = ?::jsonb,
                    budget_snapshot = ?::jsonb, item_counts = ?::jsonb,
                    llm_usage = ?::jsonb, warnings = ?::jsonb, error_code = ?,
                    agent_run_snapshot = ?::jsonb, updated_at = now()
                WHERE id = ? AND account_id = ?
                """,
                request.status(),
                request.currentPhase(),
                json(request.steps()),
                json(request.budget()),
                json(request.itemCounts()),
                json(request.llmUsage()),
                json(request.warnings()),
                request.errorCode(),
                json(request.agentRunSnapshot()),
                buildId,
                request.accountId());
        if (updated != 1) {
            throw new IllegalArgumentException("CONTEXT_BUILD_NOT_FOUND");
        }
        if (request.decisions() != null && request.decisions().isArray()) {
            jdbc.update("DELETE FROM touchstone.context_decisions WHERE context_build_id = ?", buildId);
            int order = 0;
            for (JsonNode decision : request.decisions()) {
                jdbc.update(
                        """
                        INSERT INTO touchstone.context_decisions
                            (id, context_build_id, item_key, action, reason,
                             input_tokens, output_tokens, output_content, output_hash,
                             reference_id, decision_order)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?)
                        """,
                        UUID.randomUUID(),
                        buildId,
                        text(decision, "item_id", "unknown-" + order),
                        text(decision, "action", "omitted"),
                        text(decision, "reason", ""),
                        integer(decision, "input_tokens"),
                        integer(decision, "output_tokens"),
                        jsonOrNull(decision.get("output_content")),
                        nullableText(decision, "output_hash"),
                        nullableText(decision, "source_id"),
                        order++);
            }
        }
    }

    public Optional<Map<String, Object>> findBuild(UUID accountId, UUID buildId) {
        List<Map<String, Object>> rows = jdbc.query(
                """
                SELECT id, session_id, current_request_event_id, algorithm_version,
                       status, current_phase, step_snapshot::text AS steps,
                       budget_snapshot::text AS budget, item_counts::text AS item_counts,
                       llm_usage::text AS llm_usage, warnings::text AS warnings,
                       error_code, created_at, updated_at
                FROM touchstone.context_builds
                WHERE id = ? AND account_id = ?
                """,
                this::mapBuild,
                buildId,
                accountId);
        if (rows.isEmpty()) {
            return Optional.empty();
        }
        Map<String, Object> build = rows.get(0);
        build.put("decisions", listDecisions(buildId));
        Optional<Map<String, Object>> artifact = findArtifact(accountId, buildId);
        build.put("artifactId", artifact.map(row -> row.get("artifactId")).orElse(null));
        return Optional.of(build);
    }

    public Optional<Map<String, Object>> latestBuildForSession(UUID accountId, String sessionId) {
        List<Map<String, Object>> rows = jdbc.query(
                """
                SELECT id, session_id, current_request_event_id, algorithm_version,
                       status, current_phase, error_code, created_at, updated_at
                FROM touchstone.context_builds
                WHERE account_id = ? AND session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (rs, rowNumber) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("buildId", rs.getObject("id"));
                    row.put("sessionId", rs.getString("session_id"));
                    row.put("currentRequestEventId", rs.getString("current_request_event_id"));
                    row.put("algorithmVersion", rs.getString("algorithm_version"));
                    row.put("status", rs.getString("status"));
                    row.put("currentPhase", rs.getString("current_phase"));
                    row.put("errorCode", rs.getString("error_code"));
                    row.put("createdAt", rs.getObject("created_at"));
                    row.put("updatedAt", rs.getObject("updated_at"));
                    return row;
                },
                accountId,
                sessionId);
        return rows.stream().findFirst();
    }

    public UUID saveArtifact(UUID buildId, SaveArtifactRequest request) {
        UUID artifactId = UUID.randomUUID();
        List<UUID> ids = jdbc.query(
                """
                INSERT INTO touchstone.context_artifacts
                    (id, context_build_id, account_id, message_sequence,
                     content_hash, token_count, tokenizer_version, memory_segments)
                SELECT ?, b.id, b.account_id, ?::jsonb, ?, ?, ?, ?::jsonb
                FROM touchstone.context_builds b
                WHERE b.id = ? AND b.account_id = ?
                ON CONFLICT (context_build_id) DO UPDATE SET
                    message_sequence = EXCLUDED.message_sequence,
                    content_hash = EXCLUDED.content_hash,
                    token_count = EXCLUDED.token_count,
                    tokenizer_version = EXCLUDED.tokenizer_version,
                    memory_segments = EXCLUDED.memory_segments
                RETURNING id
                """,
                (rs, rowNumber) -> rs.getObject("id", UUID.class),
                artifactId,
                json(request.messages()),
                request.contentHash(),
                request.tokenCount(),
                request.tokenizerVersion(),
                jsonArray(request.memorySegments()),
                buildId,
                request.accountId());
        if (ids.isEmpty()) {
            throw new IllegalArgumentException("CONTEXT_BUILD_NOT_FOUND");
        }
        return ids.get(0);
    }

    public Optional<Map<String, Object>> findArtifact(UUID accountId, UUID buildId) {
        List<Map<String, Object>> rows = jdbc.query(
                """
                SELECT id, context_build_id, message_sequence::text AS messages,
                       content_hash, token_count, tokenizer_version,
                       memory_segments::text AS memory_segments, created_at
                FROM touchstone.context_artifacts
                WHERE context_build_id = ? AND account_id = ? AND invalidated_at IS NULL
                """,
                (rs, rowNumber) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("artifactId", rs.getObject("id"));
                    row.put("buildId", rs.getObject("context_build_id"));
                    row.put("messages", readJson(rs.getString("messages")));
                    row.put("contentHash", rs.getString("content_hash"));
                    row.put("tokenCount", rs.getInt("token_count"));
                    row.put("tokenizerVersion", rs.getString("tokenizer_version"));
                    row.put("memorySegments", readJson(rs.getString("memory_segments")));
                    row.put("createdAt", rs.getObject("created_at"));
                    return row;
                },
                buildId,
                accountId);
        return rows.stream().findFirst();
    }

    public UUID saveMemorySegment(String sessionId, SaveMemorySegmentRequest request) {
        UUID segmentId = UUID.randomUUID();
        int inserted = jdbc.update(
                """
                INSERT INTO touchstone.context_memory_segments
                    (id, session_id, account_id, start_event_id, end_event_id,
                     source_event_ids, source_hash, source_tokens, summary_content,
                     summary_tokens, status, summary_model, prompt_version,
                     algorithm_version, generation_mode, fallback_reason, frozen_at)
                SELECT ?, s.id, s.account_id, ?, ?, ?::jsonb, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       CASE WHEN ? = 'FROZEN' THEN now() ELSE NULL END
                FROM touchstone.context_sessions s
                WHERE s.id = ? AND s.account_id = ?
                """,
                segmentId,
                request.startEventId(),
                request.endEventId(),
                json(request.sourceEventIds()),
                request.sourceHash(),
                request.sourceTokens(),
                request.summaryContent(),
                request.summaryTokens(),
                request.status(),
                request.summaryModel(),
                request.promptVersion(),
                request.algorithmVersion(),
                request.generationMode(),
                request.fallbackReason(),
                request.status(),
                sessionId,
                request.accountId());
        if (inserted != 1) {
            throw new IllegalArgumentException("CONTEXT_SESSION_NOT_FOUND");
        }
        return segmentId;
    }

    public List<Map<String, Object>> listMemorySegments(UUID accountId, String sessionId) {
        return jdbc.query(
                """
                SELECT id, start_event_id, end_event_id, source_event_ids,
                       source_hash, source_tokens, summary_content, summary_tokens,
                       status, summary_model, prompt_version, algorithm_version,
                       generation_mode, fallback_reason, frozen_at
                FROM touchstone.context_memory_segments
                WHERE account_id = ? AND session_id = ?
                  AND status IN ('VALIDATED', 'FROZEN')
                ORDER BY frozen_at NULLS LAST, created_at
                """,
                this::mapMemorySegment,
                accountId,
                sessionId);
    }

    private Map<String, Object> mapMemorySegment(ResultSet rs, int rowNumber) throws SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("segmentId", rs.getObject("id"));
        row.put("startEventId", rs.getString("start_event_id"));
        row.put("endEventId", rs.getString("end_event_id"));
        row.put("sourceEventIds", readJson(rs.getString("source_event_ids")));
        row.put("sourceHash", rs.getString("source_hash"));
        row.put("sourceTokens", rs.getInt("source_tokens"));
        row.put("summaryContent", rs.getString("summary_content"));
        row.put("summaryTokens", rs.getInt("summary_tokens"));
        row.put("status", rs.getString("status"));
        row.put("summaryModel", rs.getString("summary_model"));
        row.put("promptVersion", rs.getString("prompt_version"));
        row.put("algorithmVersion", rs.getString("algorithm_version"));
        row.put("generationMode", rs.getString("generation_mode"));
        row.put("fallbackReason", rs.getString("fallback_reason"));
        row.put("frozenAt", rs.getObject("frozen_at"));
        return row;
    }

    private Map<String, Object> mapSessionSummary(ResultSet rs, int rowNumber) throws SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("sessionId", rs.getString("id"));
        row.put("title", rs.getString("title"));
        row.put("sourceType", rs.getString("source_type"));
        row.put("sourceRef", rs.getString("source_ref"));
        row.put("sourceHash", rs.getString("source_hash"));
        row.put("sourceVersion", rs.getLong("source_version"));
        row.put("status", rs.getString("status"));
        row.put("eventCount", rs.getLong("event_count"));
        row.put("turnCount", rs.getLong("turn_count"));
        row.put("userMessageCount", rs.getLong("user_message_count"));
        row.put("defaultCurrentRequestEventId", rs.getString("default_current_request_event_id"));
        row.put("createdAt", rs.getObject("created_at"));
        row.put("updatedAt", rs.getObject("updated_at"));
        return row;
    }

    private Map<String, Object> mapEvent(ResultSet rs, int rowNumber) throws SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("eventId", rs.getString("event_id"));
        row.put("turnId", rs.getString("turn_id"));
        row.put("sequence", rs.getInt("sequence"));
        row.put("eventType", rs.getString("event_type"));
        row.put("role", rs.getString("role"));
        row.put("content", rs.getString("content"));
        row.put("contentRef", rs.getString("content_ref"));
        row.put("tokenCount", rs.getInt("token_count"));
        row.put("occurredAt", rs.getObject("occurred_at"));
        row.put("toolCallId", rs.getString("tool_call_id"));
        row.put("parentEventId", rs.getString("parent_event_id"));
        row.put("securityLevel", rs.getString("security_level"));
        row.put("contentHash", rs.getString("content_hash"));
        return row;
    }

    private Map<String, Object> mapBuild(ResultSet rs, int rowNumber) throws SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("buildId", rs.getObject("id"));
        row.put("sessionId", rs.getString("session_id"));
        row.put("currentRequestEventId", rs.getString("current_request_event_id"));
        row.put("algorithmVersion", rs.getString("algorithm_version"));
        row.put("status", rs.getString("status"));
        row.put("currentPhase", rs.getString("current_phase"));
        row.put("steps", readJson(rs.getString("steps")));
        row.put("budget", readJson(rs.getString("budget")));
        row.put("itemCounts", readJson(rs.getString("item_counts")));
        row.put("llmUsage", readJson(rs.getString("llm_usage")));
        row.put("warnings", readJson(rs.getString("warnings")));
        row.put("errorCode", rs.getString("error_code"));
        row.put("createdAt", rs.getObject("created_at"));
        row.put("updatedAt", rs.getObject("updated_at"));
        return row;
    }

    private List<Map<String, Object>> listDecisions(UUID buildId) {
        return jdbc.queryForList(
                """
                SELECT item_key, action, reason, input_tokens, output_tokens,
                       output_content, output_hash, reference_id, decision_order
                FROM touchstone.context_decisions
                WHERE context_build_id = ? ORDER BY decision_order
                """,
                buildId);
    }

    private String json(JsonNode node) {
        return node == null ? "{}" : node.toString();
    }

    private String jsonArray(JsonNode node) {
        return node == null || node.isNull() ? "[]" : node.toString();
    }

    private String jsonOrNull(JsonNode node) {
        return node == null || node.isNull() ? null : node.toString();
    }

    private JsonNode readJson(String value) throws SQLException {
        try {
            return objectMapper.readTree(value == null ? "null" : value);
        } catch (JsonProcessingException exception) {
            throw new SQLException("invalid context memory JSON", exception);
        }
    }

    private static String text(JsonNode node, String field, String fallback) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? fallback : value.asText(fallback);
    }

    private static String nullableText(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? null : value.asText();
    }

    private static int integer(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value == null ? 0 : value.asInt(0);
    }
}
