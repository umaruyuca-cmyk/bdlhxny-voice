package com.bdlh.touchstone.data.repository;

import com.bdlh.touchstone.data.domain.ContextOpsPayloads.CreateGrantRequest;
import com.bdlh.touchstone.data.domain.ContextOpsPayloads.FinishAnalysisRunRequest;
import com.bdlh.touchstone.data.domain.ContextOpsPayloads.SaveQualityCheckRequest;
import com.bdlh.touchstone.data.domain.ContextOpsPayloads.WriteAuditRequest;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.web.server.ResponseStatusException;

/**
 * 上下文工作台细粒度 RBAC 数据访问:跨所有者授权、审计(复用 audit_log)、
 * 跨所有者构建元数据行(运维脱敏视图的原始数据;脱敏由 Engine 侧裁剪),
 * 以及 P2 定时分析的采样源与结果持久化。
 */
@Repository
public class ContextOpsRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public ContextOpsRepository(JdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    /** 活跃授权重复(部分唯一索引含 NULLS NOT DISTINCT)。 */
    public static final class GrantConflict extends RuntimeException {
        public GrantConflict(String message) {
            super(message);
        }
    }

    public Map<String, Object> createGrant(CreateGrantRequest request) {
        UUID id = UUID.randomUUID();
        try {
            jdbc.update(
                    """
                    INSERT INTO touchstone.context_access_grants
                        (id, owner_account_id, grantee_account_id, scope, build_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    id,
                    request.ownerAccountId(),
                    request.granteeAccountId(),
                    request.scope(),
                    request.buildId());
        } catch (DuplicateKeyException exception) {
            throw new GrantConflict("同样的活跃授权已存在");
        }
        return findGrant(id).orElseThrow();
    }

    public List<Map<String, Object>> listGrants(UUID ownerAccountId) {
        return jdbc.query(
                """
                SELECT id, owner_account_id, grantee_account_id, scope, build_id,
                       created_at, revoked_at
                FROM touchstone.context_access_grants
                WHERE owner_account_id = ?
                ORDER BY created_at DESC
                LIMIT 200
                """,
                this::mapGrant,
                ownerAccountId);
    }

    public boolean revokeGrant(UUID ownerAccountId, UUID grantId) {
        return jdbc.update(
                """
                UPDATE touchstone.context_access_grants
                SET revoked_at = now()
                WHERE id = ? AND owner_account_id = ? AND revoked_at IS NULL
                """,
                grantId,
                ownerAccountId) > 0;
    }

    /** buildId 精确命中或全局授权(build_id IS NULL)均视为持有权限。 */
    public boolean hasActiveGrant(UUID ownerAccountId, UUID granteeAccountId, String buildId) {
        Integer count = jdbc.queryForObject(
                """
                SELECT count(*)
                FROM touchstone.context_access_grants
                WHERE owner_account_id = ?
                  AND grantee_account_id = ?
                  AND scope = 'ARTIFACT_READ'
                  AND revoked_at IS NULL
                  AND (build_id IS NULL OR build_id = ?)
                """,
                Integer.class,
                ownerAccountId,
                granteeAccountId,
                buildId);
        return count != null && count > 0;
    }

    /** 被授权方视角的权限判定(Engine 校验跨所有者下载时使用;不含 owner)。 */
    public boolean hasActiveGrantForGrantee(UUID granteeAccountId, String buildId) {
        Integer count = jdbc.queryForObject(
                """
                SELECT count(*)
                FROM touchstone.context_access_grants
                WHERE grantee_account_id = ?
                  AND scope = 'ARTIFACT_READ'
                  AND revoked_at IS NULL
                  AND (build_id IS NULL OR build_id = ?)
                """,
                Integer.class,
                granteeAccountId,
                buildId);
        return count != null && count > 0;
    }

    /**
     * 跨所有者工件读取(授权放行后由 Engine 调用;内部接口,无 owner 过滤)。
     * buildId 不是合法 UUID 时返回 empty(与 404 等价)。
     */
    public Optional<Map<String, Object>> findArtifactCrossOwner(String buildId) {
        UUID parsed;
        try {
            parsed = UUID.fromString(buildId);
        } catch (IllegalArgumentException exception) {
            return Optional.empty();
        }
        return jdbc.query(
                """
                SELECT a.id, a.context_build_id, a.account_id, a.message_sequence::text AS messages,
                       a.content_hash, a.token_count, a.tokenizer_version,
                       a.memory_segments::text AS memory_segments,
                       b.session_id, b.current_request_event_id, b.algorithm_version
                FROM touchstone.context_artifacts a
                JOIN touchstone.context_builds b ON b.id = a.context_build_id
                WHERE a.context_build_id = ?
                """,
                (rs, rowNumber) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("artifactId", rs.getObject("id"));
                    row.put("buildId", rs.getObject("context_build_id"));
                    row.put("accountId", rs.getObject("account_id"));
                    row.put("messages", rs.getString("messages"));
                    row.put("contentHash", rs.getString("content_hash"));
                    row.put("tokenCount", rs.getInt("token_count"));
                    row.put("tokenizerVersion", rs.getString("tokenizer_version"));
                    row.put("memorySegments", rs.getString("memory_segments"));
                    row.put("sessionId", rs.getString("session_id"));
                    row.put("currentRequestEventId", rs.getString("current_request_event_id"));
                    row.put("algorithmVersion", rs.getString("algorithm_version"));
                    return row;
                },
                parsed)
                .stream()
                .findFirst();
    }

    public Optional<Map<String, Object>> findGrant(UUID grantId) {
        return jdbc.query(
                        """
                        SELECT id, owner_account_id, grantee_account_id, scope, build_id,
                               created_at, revoked_at
                        FROM touchstone.context_access_grants
                        WHERE id = ?
                        """,
                        this::mapGrant,
                        grantId)
                .stream()
                .findFirst();
    }

    public void writeAudit(WriteAuditRequest request) {
        String detail = request.detail() == null ? "{}" : request.detail().toString();
        jdbc.update(
                """
                INSERT INTO touchstone.audit_log (id, account_id, action, succeeded, detail)
                VALUES (?, ?, ?, ?, ?::jsonb)
                """,
                UUID.randomUUID(),
                request.accountId(),
                request.action(),
                request.succeeded(),
                detail);
    }

    /** accountId 为 null 时返回跨所有者审计(运维视图);否则只返回该账号的审计。 */
    public List<Map<String, Object>> listAudit(UUID accountId, int limit) {
        int safeLimit = Math.min(Math.max(limit, 1), 200);
        if (accountId == null) {
            return jdbc.query(
                    """
                    SELECT a.id, a.account_id, a.action, a.succeeded, a.detail::text AS detail,
                           a.created_at
                    FROM touchstone.audit_log a
                    WHERE left(a.action, 8) = 'CONTEXT_'
                    ORDER BY a.created_at DESC
                    LIMIT ?
                    """,
                    this::mapAudit,
                    safeLimit);
        }
        return jdbc.query(
                """
                SELECT a.id, a.account_id, a.action, a.succeeded, a.detail::text AS detail,
                       a.created_at
                FROM touchstone.audit_log a
                WHERE a.account_id = ? AND left(a.action, 8) = 'CONTEXT_'
                ORDER BY a.created_at DESC
                LIMIT ?
                """,
                this::mapAudit,
                accountId,
                safeLimit);
    }

    /** 跨所有者构建元数据行(运维脱敏视图原始数据;不含消息正文与摘要)。 */
    public Map<String, Object> listBuildsCrossOwner(int limit, int cursor) {
        int safeLimit = Math.min(Math.max(limit, 1), 200);
        int safeCursor = Math.max(cursor, 0);
        List<Map<String, Object>> rows = jdbc.query(
                """
                SELECT id, session_id, account_id, status, current_phase, algorithm_version,
                       error_code, budget_snapshot::text AS budget,
                       llm_usage::text AS llm_usage, item_counts::text AS item_counts,
                       agent_run_snapshot::text AS agent_run,
                       config_snapshot::text AS config_snapshot,
                       created_at, updated_at
                FROM touchstone.context_builds
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (rs, rowNumber) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("buildId", rs.getObject("id"));
                    row.put("sessionId", rs.getString("session_id"));
                    row.put("accountId", rs.getObject("account_id"));
                    row.put("status", rs.getString("status"));
                    row.put("currentPhase", rs.getString("current_phase"));
                    row.put("algorithmVersion", rs.getString("algorithm_version"));
                    row.put("errorCode", rs.getString("error_code"));
                    row.put("budget", rs.getString("budget"));
                    row.put("llmUsage", rs.getString("llm_usage"));
                    row.put("itemCounts", rs.getString("item_counts"));
                    row.put("agentRun", rs.getString("agent_run"));
                    row.put("configSnapshot", rs.getString("config_snapshot"));
                    row.put("createdAt", rs.getObject("created_at"));
                    row.put("updatedAt", rs.getObject("updated_at"));
                    return row;
                },
                safeLimit,
                safeCursor);
        Long total = jdbc.queryForObject("SELECT count(*) FROM touchstone.context_builds", Long.class);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("builds", rows);
        result.put("total", total == null ? 0 : total);
        result.put("nextCursor", safeCursor + rows.size() < (total == null ? 0 : total)
                ? safeCursor + rows.size() : null);
        return result;
    }

    // ── P2 定时分析:采样源、抽检结果、分析运行 ──

    /**
     * 跨所有者最近可用摘要段(评审采样源):连同来源事件正文
     * (按 source_event_ids 关联 session_events,保持顺序)一并返回。
     * 内部接口,仅供 Engine 分析任务使用。
     */
    public List<Map<String, Object>> listRecentSegmentsCrossOwner(int limit) {
        int safeLimit = Math.min(Math.max(limit, 1), 50);
        return jdbc.query(
                """
                SELECT m.id::text AS segment_id, m.session_id, m.account_id,
                       m.start_event_id, m.end_event_id, m.source_event_ids::text AS source_event_ids,
                       m.source_hash, m.source_tokens, m.summary_content, m.summary_tokens,
                       m.status, m.created_at,
                       COALESCE(src.contents, '[]') AS source_contents
                FROM touchstone.context_memory_segments m
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(e.content ORDER BY e.sequence) AS contents
                    FROM touchstone.session_events e
                    JOIN jsonb_array_elements_text(m.source_event_ids) AS sids(event_id)
                         ON e.event_id = sids.event_id
                    WHERE e.session_id = m.session_id
                ) src ON TRUE
                WHERE m.status IN ('FROZEN', 'VALIDATED')
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (rs, rowNumber) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("segmentId", rs.getString("segment_id"));
                    row.put("sessionId", rs.getString("session_id"));
                    row.put("accountId", rs.getObject("account_id"));
                    row.put("startEventId", rs.getString("start_event_id"));
                    row.put("endEventId", rs.getString("end_event_id"));
                    row.put("sourceEventIds", rs.getString("source_event_ids"));
                    row.put("sourceHash", rs.getString("source_hash"));
                    row.put("sourceTokens", rs.getInt("source_tokens"));
                    row.put("summaryContent", rs.getString("summary_content"));
                    row.put("summaryTokens", rs.getInt("summary_tokens"));
                    row.put("status", rs.getString("status"));
                    row.put("createdAt", rs.getObject("created_at"));
                    row.put("sourceContents", rs.getString("source_contents"));
                    return row;
                },
                safeLimit);
    }

    /** 保存一条摘要段语义抽检结果;verdict 只能是 PASS/WARN/FAIL/ERROR。 */
    public Map<String, Object> saveQualityCheck(SaveQualityCheckRequest request) {
        UUID id = UUID.randomUUID();
        jdbc.update(
                """
                INSERT INTO touchstone.context_segment_quality_checks
                    (id, segment_id, session_id, account_id, verdict, missing_facts,
                     hallucinations, judge_model, prompt_version, source_hash_at_check,
                     error_code, detail)
                VALUES (?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?, ?, ?::jsonb)
                """,
                id,
                request.segmentId(),
                request.sessionId(),
                request.accountId(),
                request.verdict(),
                jsonOrEmptyArray(request.missingFacts()),
                jsonOrEmptyArray(request.hallucinations()),
                request.judgeModel(),
                request.promptVersion(),
                request.sourceHashAtCheck(),
                request.errorCode(),
                jsonOrEmptyObject(request.detail()));
        return Map.of("checkId", id, "verdict", request.verdict());
    }

    /** 抽检结果查询:accountId/sessionId 均可选;两者都缺省=跨所有者(运维)。 */
    public List<Map<String, Object>> listQualityChecks(UUID accountId, String sessionId, int limit) {
        int safeLimit = Math.min(Math.max(limit, 1), 200);
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        List<Object> params = new ArrayList<>();
        if (accountId != null) {
            where.append(" AND account_id = ?");
            params.add(accountId);
        }
        if (sessionId != null && !sessionId.isBlank()) {
            where.append(" AND session_id = ?");
            params.add(sessionId);
        }
        params.add(safeLimit);
        return jdbc.query(
                """
                SELECT id, segment_id, session_id, account_id, verdict,
                       missing_facts::text AS missing_facts,
                       hallucinations::text AS hallucinations,
                       judge_model, prompt_version, source_hash_at_check, error_code,
                       detail::text AS detail, created_at
                FROM touchstone.context_segment_quality_checks"""
                        + where
                        + " ORDER BY created_at DESC LIMIT ?",
                this::mapQualityCheck,
                params.toArray());
    }

    /** 创建分析运行行(RUNNING);返回运行 ID。 */
    public UUID startAnalysisRun(String triggerSource) {
        UUID id = UUID.randomUUID();
        jdbc.update(
                """
                INSERT INTO touchstone.context_analysis_runs (id, status, trigger_source)
                VALUES (?, 'RUNNING', ?)
                """,
                id,
                triggerSource);
        return id;
    }

    /** 写入分析运行终态(COMPLETED/FAILED)与报告。 */
    public boolean finishAnalysisRun(UUID runId, FinishAnalysisRunRequest request) {
        int updated = jdbc.update(
                """
                UPDATE touchstone.context_analysis_runs
                SET status = ?, sampled_segments = ?, judge_calls = ?, judge_errors = ?,
                    report = ?::jsonb, error_code = ?, finished_at = now()
                WHERE id = ?
                """,
                request.status(),
                request.sampledSegments() == null ? 0 : request.sampledSegments(),
                request.judgeCalls() == null ? 0 : request.judgeCalls(),
                request.judgeErrors() == null ? 0 : request.judgeErrors(),
                jsonOrEmptyObject(request.report()),
                request.errorCode(),
                runId);
        return updated > 0;
    }

    public List<Map<String, Object>> listAnalysisRuns(int limit) {
        int safeLimit = Math.min(Math.max(limit, 1), 50);
        return jdbc.query(
                """
                SELECT id, status, trigger_source, sampled_segments, judge_calls,
                       judge_errors, report::text AS report, error_code,
                       started_at, finished_at
                FROM touchstone.context_analysis_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (rs, rowNumber) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("runId", rs.getObject("id"));
                    row.put("status", rs.getString("status"));
                    row.put("triggerSource", rs.getString("trigger_source"));
                    row.put("sampledSegments", rs.getInt("sampled_segments"));
                    row.put("judgeCalls", rs.getInt("judge_calls"));
                    row.put("judgeErrors", rs.getInt("judge_errors"));
                    row.put("report", rs.getString("report"));
                    row.put("errorCode", rs.getString("error_code"));
                    row.put("startedAt", rs.getObject("started_at"));
                    row.put("finishedAt", rs.getObject("finished_at"));
                    return row;
                },
                safeLimit);
    }

    private Map<String, Object> mapQualityCheck(java.sql.ResultSet rs, int rowNumber) throws java.sql.SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("checkId", rs.getObject("id"));
        row.put("segmentId", rs.getString("segment_id"));
        row.put("sessionId", rs.getString("session_id"));
        row.put("accountId", rs.getObject("account_id"));
        row.put("verdict", rs.getString("verdict"));
        row.put("missingFacts", rs.getString("missing_facts"));
        row.put("hallucinations", rs.getString("hallucinations"));
        row.put("judgeModel", rs.getString("judge_model"));
        row.put("promptVersion", rs.getString("prompt_version"));
        row.put("sourceHashAtCheck", rs.getString("source_hash_at_check"));
        row.put("errorCode", rs.getString("error_code"));
        row.put("detail", rs.getString("detail"));
        row.put("createdAt", rs.getObject("created_at"));
        return row;
    }

    private String jsonOrEmptyArray(List<String> value) {
        if (value == null) {
            return "[]";
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (com.fasterxml.jackson.core.JsonProcessingException exception) {
            throw new IllegalArgumentException("missing facts is not serializable", exception);
        }
    }

    private String jsonOrEmptyObject(Object value) {
        if (value == null) {
            return "{}";
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (com.fasterxml.jackson.core.JsonProcessingException exception) {
            throw new IllegalArgumentException("detail is not valid JSON", exception);
        }
    }

    private Map<String, Object> mapGrant(java.sql.ResultSet rs, int rowNumber) throws java.sql.SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("grantId", rs.getObject("id"));
        row.put("ownerAccountId", rs.getObject("owner_account_id"));
        row.put("granteeAccountId", rs.getObject("grantee_account_id"));
        row.put("scope", rs.getString("scope"));
        row.put("buildId", rs.getString("build_id"));
        row.put("createdAt", rs.getObject("created_at"));
        row.put("revokedAt", rs.getObject("revoked_at"));
        return row;
    }

    private Map<String, Object> mapAudit(java.sql.ResultSet rs, int rowNumber) throws java.sql.SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("auditId", rs.getObject("id"));
        row.put("accountId", rs.getObject("account_id"));
        row.put("action", rs.getString("action"));
        row.put("succeeded", rs.getBoolean("succeeded"));
        row.put("detail", rs.getString("detail"));
        row.put("createdAt", rs.getObject("created_at"));
        return row;
    }

    /** 供控制器把冲突映射为 409(避免仓库层依赖 HTTP 语义)。 */
    public static ResponseStatusException conflict(GrantConflict exception) {
        return new ResponseStatusException(HttpStatus.CONFLICT, exception.getMessage(), exception);
    }
}
