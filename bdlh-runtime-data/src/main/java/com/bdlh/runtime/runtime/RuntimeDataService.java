package com.bdlh.runtime.runtime;

import com.bdlh.runtime.runtime.RuntimeDataDtos.AnalysisHistoryResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.ChatMessageRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.ChatMessageResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.ChatSessionResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.PendingRunRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.RunLocationResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.RunEventResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.RunProjectionResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.SaveHistoryRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.SaveRunProjectionRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.UpsertRunRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.VerifiedEntityRequest;
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
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

@Service
public class RuntimeDataService {

    private static final String DEFAULT_TITLE = "新的对话";
    private static final String DEFAULT_RUNTIME_PATH = "legacy_root_graph";
    private static final Set<String> HISTORY_STATUSES = Set.of(
            "SUCCESS", "PARTIAL", "LIMITED", "FAILED", "RUNNING");

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public RuntimeDataService(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @Transactional
    public ChatSessionResponse ensureSession(long userId, String requestedSessionId) {
        String requested = normalizedNullable(requestedSessionId);
        if (requested != null) {
            ChatSessionResponse existing = findSession(userId, requested);
            if (existing != null) {
                return existing;
            }
        }
        String sessionId = requested != null ? requested : UUID.randomUUID().toString();
        jdbcTemplate.update(
                "INSERT INTO runtime.chat_session(user_id, session_id) VALUES (?, ?)",
                userId,
                sessionId);
        return requireSession(userId, sessionId);
    }

    public List<ChatSessionResponse> listSessions(long userId, int requestedLimit) {
        int limit = Math.min(Math.max(requestedLimit, 1), 100);
        List<String> sessionIds = jdbcTemplate.query(
                "SELECT session_id FROM runtime.chat_session WHERE user_id = ? "
                        + "ORDER BY updated_at DESC, session_id DESC LIMIT ?",
                (rs, rowNum) -> rs.getString(1),
                userId,
                limit);
        return sessionIds.stream().map(sessionId -> requireSession(userId, sessionId)).toList();
    }

    public ChatSessionResponse getSession(long userId, String sessionId) {
        return requireSession(userId, requiredValue(sessionId, "session_id"));
    }

    @Transactional
    public ChatSessionResponse appendMessage(long userId, String sessionId, ChatMessageRequest request) {
        String id = requiredValue(sessionId, "session_id");
        String role = requiredValue(request.role(), "role");
        String content = requiredValue(request.content(), "content");
        ChatSessionResponse session = requireSession(userId, id);
        jdbcTemplate.update(
                "INSERT INTO runtime.chat_message(user_id, session_id, role, content) VALUES (?, ?, ?, ?)",
                userId,
                id,
                role,
                content);
        String title = session.title();
        if ("user".equals(role) && DEFAULT_TITLE.equals(title)) {
            title = compactTitle(content);
        }
        jdbcTemplate.update(
                "UPDATE runtime.chat_session SET title = ?, updated_at = CURRENT_TIMESTAMP "
                        + "WHERE user_id = ? AND session_id = ?",
                title,
                userId,
                id);
        return requireSession(userId, id);
    }

    @Transactional
    public ChatSessionResponse prepareRegeneration(long userId, String sessionId) {
        String id = requiredValue(sessionId, "session_id");
        requireSession(userId, id);
        jdbcTemplate.update(
                "DELETE FROM runtime.chat_message WHERE message_id = ("
                        + "SELECT message_id FROM runtime.chat_message "
                        + "WHERE user_id = ? AND session_id = ? ORDER BY message_id DESC LIMIT 1"
                        + ") AND role = 'assistant'",
                userId,
                id);
        touchSession(userId, id);
        return requireSession(userId, id);
    }

    @Transactional
    public ChatSessionResponse setPending(long userId, String sessionId, PendingRunRequest request) {
        String id = requiredValue(sessionId, "session_id");
        requireSession(userId, id);
        jdbcTemplate.update(
                "UPDATE runtime.chat_session SET pending_run_id = ?, pending_thread_id = ?, "
                        + "pending_checkpoint_id = ?, pending_runtime_path = ?, pause_reason = ?, "
                        + "awaiting_route_confirm = ?, updated_at = CURRENT_TIMESTAMP "
                        + "WHERE user_id = ? AND session_id = ?",
                normalizedNullable(request.runId()),
                normalizedNullable(request.threadId()),
                normalizedNullable(request.checkpointId()),
                normalizedNullable(request.runtimePath()),
                request.runId() == null || request.runId().isBlank()
                        ? null
                        : normalizedNullable(request.pauseReason()),
                request.runId() != null
                        && !request.runId().isBlank()
                        && Boolean.TRUE.equals(request.awaitingRouteConfirm()),
                userId,
                id);
        return requireSession(userId, id);
    }

    @Transactional
    public ChatSessionResponse setVerifiedEntity(
            long userId, String sessionId, VerifiedEntityRequest request) {
        String id = requiredValue(sessionId, "session_id");
        requireSession(userId, id);
        JsonNode state = request == null ? null : request.verifiedEntityState();
        if (state != null && state.isNull()) {
            state = null;
        }
        jdbcTemplate.update(
                "UPDATE runtime.chat_session SET verified_entity_state = ?::jsonb, "
                        + "updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND session_id = ?",
                state == null ? null : writeJson(state),
                userId,
                id);
        return requireSession(userId, id);
    }

    @Transactional
    public boolean deleteSession(long userId, String sessionId) {
        return jdbcTemplate.update(
                "DELETE FROM runtime.chat_session WHERE user_id = ? AND session_id = ?",
                userId,
                requiredValue(sessionId, "session_id")) > 0;
    }

    @Transactional
    public RunLocationResponse upsertRun(long userId, String runId, UpsertRunRequest request) {
        String id = requiredValue(runId, "run_id");
        String threadId = requiredValue(request.threadId(), "thread_id");
        String runtimePath = normalizedNullable(request.runtimePath());
        jdbcTemplate.update(
                "INSERT INTO runtime.run_registry(run_id, user_id, thread_id, checkpoint_id, runtime_path) "
                        + "VALUES (?, ?, ?, ?, ?) ON CONFLICT (run_id) DO UPDATE SET "
                        + "user_id = EXCLUDED.user_id, thread_id = EXCLUDED.thread_id, "
                        + "checkpoint_id = EXCLUDED.checkpoint_id, runtime_path = EXCLUDED.runtime_path, "
                        + "updated_at = CURRENT_TIMESTAMP",
                id,
                userId,
                threadId,
                normalizedNullable(request.checkpointId()),
                runtimePath == null ? DEFAULT_RUNTIME_PATH : runtimePath);
        return requireRun(userId, id);
    }

    public RunLocationResponse getRun(long userId, String runId) {
        return requireRun(userId, requiredValue(runId, "run_id"));
    }

    @Transactional
    public RunProjectionResponse saveRunProjection(
            long userId,
            String runId,
            SaveRunProjectionRequest request) {
        String id = requiredValue(runId, "run_id");
        String threadId = requiredValue(request.threadId(), "thread_id");
        String status = requiredValue(request.status(), "status");
        JsonNode interrupts = request.interrupts() == null ? objectMapper.createArrayNode() : request.interrupts();
        jdbcTemplate.update(
                "INSERT INTO runtime.run_projection(run_id, user_id, thread_id, status, next_stage, final_response, interrupts) "
                        + "VALUES (?, ?, ?, ?, ?, ?::jsonb, ?::jsonb) ON CONFLICT (run_id) DO UPDATE SET "
                        + "user_id = EXCLUDED.user_id, thread_id = EXCLUDED.thread_id, status = EXCLUDED.status, "
                        + "next_stage = EXCLUDED.next_stage, final_response = EXCLUDED.final_response, "
                        + "interrupts = EXCLUDED.interrupts, updated_at = CURRENT_TIMESTAMP",
                id,
                userId,
                threadId,
                status,
                normalizedNullable(request.nextStage()),
                request.finalResponse() == null ? null : writeJson(request.finalResponse()),
                writeJson(interrupts));
        jdbcTemplate.update("DELETE FROM runtime.run_event WHERE run_id = ?", id);
        List<RuntimeDataDtos.RunEventRequest> events = request.events() == null ? List.of() : request.events();
        for (int index = 0; index < events.size(); index++) {
            RuntimeDataDtos.RunEventRequest event = events.get(index);
            jdbcTemplate.update(
                    "INSERT INTO runtime.run_event(run_id, sequence_no, event_type, payload) VALUES (?, ?, ?, ?::jsonb)",
                    id,
                    index,
                    requiredValue(event.eventType(), "event_type"),
                    writeJson(event.payload() == null ? objectMapper.createObjectNode() : event.payload()));
        }
        return requireRunProjection(userId, id);
    }

    public RunProjectionResponse getRunProjection(long userId, String runId) {
        return requireRunProjection(userId, requiredValue(runId, "run_id"));
    }

    @Transactional
    public AnalysisHistoryResponse saveHistory(
            long userId,
            String historyId,
            SaveHistoryRequest request) {
        String id = requiredValue(historyId, "history_id");
        String threadId = requiredValue(request.threadId(), "thread_id");
        String runId = requiredValue(request.runId(), "run_id");
        String status = requiredValue(request.status(), "status").toUpperCase(Locale.ROOT);
        if (!HISTORY_STATUSES.contains(status)) {
            throw badRequest("status 不受支持");
        }
        if (request.payload() == null || request.payload().isNull()) {
            throw badRequest("payload 不能为空");
        }
        OffsetDateTime createdAt = request.createdAt() == null
                ? OffsetDateTime.now(ZoneOffset.UTC)
                : request.createdAt();
        jdbcTemplate.update(
                "INSERT INTO runtime.analysis_history(history_id, user_id, thread_id, run_id, status, payload, created_at) "
                        + "VALUES (?, ?, ?, ?, ?, ?::jsonb, ?) ON CONFLICT (history_id) DO UPDATE SET "
                        + "user_id = EXCLUDED.user_id, thread_id = EXCLUDED.thread_id, run_id = EXCLUDED.run_id, "
                        + "status = EXCLUDED.status, payload = EXCLUDED.payload",
                id,
                userId,
                threadId,
                runId,
                status,
                writeJson(request.payload()),
                createdAt);
        return requireHistory(userId, id);
    }

    public AnalysisHistoryResponse getHistory(long userId, String historyId) {
        return requireHistory(userId, requiredValue(historyId, "history_id"));
    }

    public List<AnalysisHistoryResponse> listHistory(long userId, String threadId) {
        String id = requiredValue(threadId, "thread_id");
        return jdbcTemplate.query(
                "SELECT history_id, thread_id, run_id, status, payload, created_at "
                        + "FROM runtime.analysis_history WHERE user_id = ? AND thread_id = ? "
                        + "ORDER BY created_at ASC, history_id ASC",
                this::mapHistory,
                userId,
                id);
    }

    private ChatSessionResponse requireSession(long userId, String sessionId) {
        ChatSessionResponse session = findSession(userId, sessionId);
        if (session == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "聊天会话不存在或无权访问");
        }
        return session;
    }

    private ChatSessionResponse findSession(long userId, String sessionId) {
        List<SessionRow> results = jdbcTemplate.query(
                "SELECT session_id, title, pending_run_id, pending_thread_id, pending_checkpoint_id, "
                        + "pending_runtime_path, pause_reason, awaiting_route_confirm, "
                        + "verified_entity_state, updated_at "
                        + "FROM runtime.chat_session "
                        + "WHERE user_id = ? AND session_id = ?",
                (rs, rowNum) -> new SessionRow(
                        rs.getString("session_id"),
                        rs.getString("title"),
                        rs.getString("pending_run_id"),
                        rs.getString("pending_thread_id"),
                        rs.getString("pending_checkpoint_id"),
                        rs.getString("pending_runtime_path"),
                        rs.getString("pause_reason"),
                        rs.getBoolean("awaiting_route_confirm"),
                        readJsonNullable(rs.getString("verified_entity_state")),
                        rs.getObject("updated_at", OffsetDateTime.class)),
                userId,
                sessionId);
        if (results.isEmpty()) {
            return null;
        }
        SessionRow row = results.get(0);
        List<ChatMessageResponse> messages = jdbcTemplate.query(
                "SELECT role, content, created_at FROM runtime.chat_message "
                        + "WHERE user_id = ? AND session_id = ? ORDER BY message_id ASC",
                (rs, rowNum) -> new ChatMessageResponse(
                        rs.getString("role"),
                        rs.getString("content"),
                        rs.getObject("created_at", OffsetDateTime.class)),
                userId,
                sessionId);
        return new ChatSessionResponse(
                row.sessionId(),
                row.title(),
                messages,
                row.pendingRunId(),
                row.pendingThreadId(),
                row.pendingCheckpointId(),
                row.pendingRuntimePath(),
                row.pauseReason(),
                row.awaitingRouteConfirm(),
                row.verifiedEntityState(),
                row.updatedAt());
    }

    private RunLocationResponse requireRun(long userId, String runId) {
        List<RunLocationResponse> results = jdbcTemplate.query(
                "SELECT run_id, thread_id, checkpoint_id, runtime_path, updated_at "
                        + "FROM runtime.run_registry WHERE user_id = ? AND run_id = ?",
                (rs, rowNum) -> new RunLocationResponse(
                        rs.getString("run_id"),
                        rs.getString("thread_id"),
                        rs.getString("checkpoint_id"),
                        rs.getString("runtime_path"),
                        rs.getObject("updated_at", OffsetDateTime.class)),
                userId,
                runId);
        if (results.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "运行记录不存在或无权访问");
        }
        return results.get(0);
    }

    private RunProjectionResponse requireRunProjection(long userId, String runId) {
        List<RunProjectionResponse> results = jdbcTemplate.query(
                "SELECT run_id, thread_id, status, next_stage, final_response, interrupts, updated_at "
                        + "FROM runtime.run_projection WHERE user_id = ? AND run_id = ?",
                (rs, rowNum) -> new ProjectionRow(
                        rs.getString("run_id"),
                        rs.getString("thread_id"),
                        rs.getString("status"),
                        rs.getString("next_stage"),
                        readJson(rs.getString("final_response")),
                        readJson(rs.getString("interrupts")),
                        rs.getObject("updated_at", OffsetDateTime.class)),
                userId,
                runId).stream().map(row -> new RunProjectionResponse(
                        row.runId(),
                        row.threadId(),
                        row.status(),
                        row.nextStage(),
                        row.finalResponse(),
                        row.interrupts(),
                        jdbcTemplate.query(
                                "SELECT sequence_no, event_type, payload, created_at FROM runtime.run_event "
                                        + "WHERE run_id = ? ORDER BY sequence_no ASC",
                                (eventRs, eventRowNum) -> new RunEventResponse(
                                        eventRs.getInt("sequence_no"),
                                        eventRs.getString("event_type"),
                                        readJson(eventRs.getString("payload")),
                                        eventRs.getObject("created_at", OffsetDateTime.class)),
                                row.runId()),
                        row.updatedAt())).toList();
        if (results.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "运行投影不存在或无权访问");
        }
        return results.get(0);
    }

    private AnalysisHistoryResponse requireHistory(long userId, String historyId) {
        List<AnalysisHistoryResponse> results = jdbcTemplate.query(
                "SELECT history_id, thread_id, run_id, status, payload, created_at "
                        + "FROM runtime.analysis_history WHERE user_id = ? AND history_id = ?",
                this::mapHistory,
                userId,
                historyId);
        if (results.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "分析历史不存在或无权访问");
        }
        return results.get(0);
    }

    private record ProjectionRow(
            String runId,
            String threadId,
            String status,
            String nextStage,
            JsonNode finalResponse,
            JsonNode interrupts,
            OffsetDateTime updatedAt) {
    }

    private AnalysisHistoryResponse mapHistory(ResultSet rs, int rowNum) throws SQLException {
        return new AnalysisHistoryResponse(
                rs.getString("history_id"),
                rs.getString("thread_id"),
                rs.getString("run_id"),
                rs.getString("status"),
                readJson(rs.getString("payload")),
                rs.getObject("created_at", OffsetDateTime.class));
    }

    private void touchSession(long userId, String sessionId) {
        jdbcTemplate.update(
                "UPDATE runtime.chat_session SET updated_at = CURRENT_TIMESTAMP "
                        + "WHERE user_id = ? AND session_id = ?",
                userId,
                sessionId);
    }

    private String writeJson(JsonNode value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw badRequest("payload 无法序列化");
        }
    }

    private JsonNode readJson(String value) {
        try {
            return objectMapper.readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("数据库中的 History payload 非法", exception);
        }
    }

    private JsonNode readJsonNullable(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return readJson(value);
    }

    private static String requiredValue(String value, String field) {
        String normalized = normalizedNullable(value);
        if (normalized == null) {
            throw badRequest(field + " 不能为空");
        }
        return normalized;
    }

    private static String normalizedNullable(String value) {
        if (value == null) {
            return null;
        }
        String normalized = value.trim();
        return normalized.isEmpty() ? null : normalized;
    }

    private static String compactTitle(String content) {
        return content.length() <= 24 ? content : content.substring(0, 24) + "…";
    }

    private static ResponseStatusException badRequest(String reason) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, reason);
    }

    private record SessionRow(
            String sessionId,
            String title,
            String pendingRunId,
            String pendingThreadId,
            String pendingCheckpointId,
            String pendingRuntimePath,
            String pauseReason,
            boolean awaitingRouteConfirm,
            JsonNode verifiedEntityState,
            OffsetDateTime updatedAt) {
    }
}
