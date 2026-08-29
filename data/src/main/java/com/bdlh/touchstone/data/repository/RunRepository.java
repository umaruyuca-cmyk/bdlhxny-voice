package com.bdlh.touchstone.data.repository;

import static com.bdlh.touchstone.data.domain.RunPayloads.*;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class RunRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public RunRepository(JdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    public UUID createBatch(CreateBatchRequest request) {
        UUID id = UUID.randomUUID();
        jdbc.update(
                """
                INSERT INTO touchstone.run_batches
                    (id, name, experiment_type, fixed_conditions, status)
                VALUES (?, ?, ?, ?::jsonb, 'RUNNING')
                """,
                id,
                request.name(),
                request.experimentType(),
                json(request.fixedConditions()));
        return id;
    }

    public UUID createRun(CreateRunRequest request) {
        UUID id = UUID.randomUUID();
        jdbc.update(
                """
                INSERT INTO touchstone.agent_runs
                    (id, batch_id, case_id, case_version, variant_id, snapshot_id,
                     agent_mode, context_strategy, model, model_config, git_commit, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, 'CREATED')
                """,
                id,
                request.batchId(),
                request.caseId(),
                request.caseVersion(),
                request.variantId(),
                request.snapshotId(),
                request.agentMode(),
                request.contextStrategy(),
                request.model(),
                jsonOrEmpty(request.modelConfig()),
                request.gitCommit());
        return id;
    }

    public void completeBatch(UUID batchId, CompleteBatchRequest request) {
        if (!List.of("COMPLETE", "FAILED", "CANCELLED").contains(request.status())) {
            throw new IllegalArgumentException("invalid terminal batch status: " + request.status());
        }
        int updated = jdbc.update(
                """
                UPDATE touchstone.run_batches
                SET status = ?, completed_at = now()
                WHERE id = ?
                """,
                request.status(),
                batchId);
        if (updated == 0) {
            throw new IllegalArgumentException("unknown batch_id: " + batchId);
        }
    }

    /**
     * 批次执行报告落库(报告为执行器完整 payload JSON)。
     * 报告是批次详情页压缩明细/汇总的第一读取来源;完成时由 engine 写入。
     */
    public void saveBatchReport(UUID batchId, SaveBatchReportRequest request) {
        int updated = jdbc.update(
                """
                UPDATE touchstone.run_batches
                SET report = ?::jsonb
                WHERE id = ?
                """,
                request.report().toString(),
                batchId);
        if (updated == 0) {
            throw new IllegalArgumentException("unknown batch_id: " + batchId);
        }
    }

    /** 读取批次执行报告;空报告({})按不存在处理,由调用方回退本地工件。 */
    public JsonNode getBatchReport(UUID batchId) {
        String text = jdbc.queryForObject(
                """
                SELECT report::text FROM touchstone.run_batches WHERE id = ?
                """,
                String.class,
                batchId);
        if (text == null || text.isBlank() || "{}".equals(text.trim())) {
            return null;
        }
        try {
            return objectMapper.readTree(text);
        } catch (JsonProcessingException exception) {
            return null;
        }
    }

    /**
     * 批次列表(所有者视角,新到旧 keyset 分页)。
     *
     * cursor = 上一页最后一条批次 id;按 (created_at, id) 二元组比较翻页。
     * 模板口径列(template_id / template_classification / independent_variable /
     * repeat_count / variant_count)从 fixed_conditions JSONB 提取,历史批次
     * (无模板键)为 null,由调用方按「旧实验定义」展示。
     */
    public Map<String, Object> listBatches(int limit, UUID cursor) {
        String sql =
                """
                SELECT b.id, b.name, b.experiment_type, b.status, b.created_at, b.completed_at,
                       b.fixed_conditions->>'template_id' AS template_id,
                       b.fixed_conditions->>'template_classification' AS template_classification,
                       array_to_string(ARRAY(
                           SELECT jsonb_array_elements_text(
                               COALESCE(b.fixed_conditions->'independent_variable', '[]'::jsonb))
                       ), ', ') AS independent_variable,
                       (b.fixed_conditions->>'repeat_count')::int AS repeat_count,
                       jsonb_array_length(COALESCE(b.fixed_conditions->'variant_labels', '[]'::jsonb)) AS variant_count,
                       (SELECT count(*) FROM touchstone.agent_runs r WHERE r.batch_id = b.id) AS run_count
                FROM touchstone.run_batches b
                """;
        List<Map<String, Object>> rows;
        if (cursor == null) {
            rows = jdbc.query(
                    sql + " ORDER BY b.created_at DESC, b.id DESC LIMIT ?",
                    this::mapBatchSummaryRow,
                    limit);
        } else {
            rows = jdbc.query(
                    sql
                            + """
                              WHERE (b.created_at, b.id) < (
                                  SELECT z.created_at, z.id FROM touchstone.run_batches z WHERE z.id = ?
                              )
                              ORDER BY b.created_at DESC, b.id DESC LIMIT ?
                              """,
                    this::mapBatchSummaryRow,
                    cursor,
                    limit);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("batches", rows);
        payload.put("nextCursor", rows.size() == limit ? rows.get(rows.size() - 1).get("id") : null);
        return payload;
    }

    private Map<String, Object> mapBatchSummaryRow(java.sql.ResultSet rs, int rowNumber) throws java.sql.SQLException {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", rs.getObject("id"));
        row.put("name", rs.getString("name"));
        row.put("experimentType", rs.getString("experiment_type"));
        row.put("templateId", rs.getString("template_id"));
        row.put("templateClassification", rs.getString("template_classification"));
        row.put("independentVariable", rs.getString("independent_variable"));
        row.put("repeatCount", rs.getObject("repeat_count"));
        row.put("variantCount", rs.getObject("variant_count"));
        row.put("runCount", rs.getObject("run_count"));
        row.put("status", rs.getString("status"));
        row.put("createdAt", rs.getObject("created_at"));
        row.put("completedAt", rs.getObject("completed_at"));
        return row;
    }

    public Map<String, Object> getBatch(UUID batchId) {
        Map<String, Object> batch = jdbc.queryForObject(
                """
                SELECT id, name, experiment_type, fixed_conditions::text AS fixed_conditions,
                       status, created_at, completed_at
                FROM touchstone.run_batches WHERE id = ?
                """,
                (rs, rowNumber) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("id", rs.getObject("id"));
                    row.put("name", rs.getString("name"));
                    row.put("experimentType", rs.getString("experiment_type"));
                    try {
                        row.put("fixedConditions", objectMapper.readTree(rs.getString("fixed_conditions")));
                    } catch (JsonProcessingException exception) {
                        throw new java.sql.SQLException("invalid batch fixed_conditions JSON", exception);
                    }
                    row.put("status", rs.getString("status"));
                    row.put("createdAt", rs.getObject("created_at"));
                    row.put("completedAt", rs.getObject("completed_at"));
                    return row;
                },
                batchId);
        batch.put(
                "runs",
                jdbc.queryForList(
                        """
                        SELECT id, case_id, case_version, variant_id, agent_mode,
                               context_strategy, model, model_config::text AS model_config,
                               status, error_category, created_at, completed_at
                        FROM touchstone.agent_runs
                        WHERE batch_id = ?
                        ORDER BY case_id, agent_mode
                        """,
                        batchId)
                        .stream()
                        .map(row -> {
                            Object configText = row.get("model_config");
                            if (configText != null) {
                                try {
                                    row.put(
                                            "modelConfig",
                                            objectMapper.readTree(String.valueOf(configText)));
                                } catch (JsonProcessingException exception) {
                                    throw new IllegalStateException(
                                            "invalid run model_config JSON", exception);
                                }
                            } else {
                                row.put("modelConfig", null);
                            }
                            row.remove("model_config");
                            return row;
                        })
                        .toList());
        return batch;
    }

    @Transactional
    public UUID saveContextBuild(UUID runId, SaveContextBuildRequest request) {
        UUID buildId = UUID.randomUUID();
        jdbc.update(
                """
                INSERT INTO touchstone.context_builds
                    (id, run_id, strategy, tokenizer_version, compression_version,
                     token_budget, original_tokens, working_tokens,
                     compression_input_tokens, compression_output_tokens, duration_ms,
                     required_retained, budget_fit, references_valid, instruction_isolated,
                     status, error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                buildId,
                runId,
                request.strategy(),
                request.tokenizerVersion(),
                request.compressionVersion(),
                request.tokenBudget(),
                request.originalTokens(),
                request.workingTokens(),
                request.compressionInputTokens(),
                request.compressionOutputTokens(),
                request.durationMs(),
                request.requiredRetained(),
                request.budgetFit(),
                request.referencesValid(),
                request.instructionIsolated(),
                request.status(),
                request.errorCode());

        for (ContextItemInput item : request.items()) {
            jdbc.update(
                    """
                    INSERT INTO touchstone.context_items
                        (id, context_build_id, item_key, item_type, classification,
                         content, content_ref, source_id, owner_id, observed_at,
                         valid_from, valid_to, priority, trusted, raw_tokens,
                         content_hash, sequence)
                    VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    UUID.randomUUID(),
                    buildId,
                    item.itemKey(),
                    item.itemType(),
                    item.classification(),
                    json(item.content()),
                    item.contentRef(),
                    item.sourceId(),
                    item.ownerId(),
                    item.observedAt(),
                    item.validFrom(),
                    item.validTo(),
                    item.priority(),
                    item.trusted(),
                    item.rawTokens(),
                    item.contentHash(),
                    item.sequence());
        }

        for (ContextDecisionInput decision : request.decisions()) {
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
                    decision.itemKey(),
                    decision.action(),
                    decision.reason(),
                    decision.inputTokens(),
                    decision.outputTokens(),
                    jsonOrNull(decision.outputContent()),
                    decision.outputHash(),
                    decision.referenceId(),
                    decision.decisionOrder());
        }

        for (ContextMessageInput message : request.messages()) {
            jdbc.update(
                    """
                    INSERT INTO touchstone.context_messages
                        (id, context_build_id, message_order, role, content,
                         content_hash, tokens)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    UUID.randomUUID(),
                    buildId,
                    message.messageOrder(),
                    message.role(),
                    message.content(),
                    message.contentHash(),
                    message.tokens());
        }
        return buildId;
    }

    @Transactional
    public void saveEvents(UUID runId, SaveEventsRequest request) {
        for (RunEventInput event : request.events()) {
            jdbc.update(
                    """
                    INSERT INTO touchstone.run_events
                        (id, run_id, sequence, event_type, payload, occurred_at)
                    VALUES (?, ?, ?, ?, ?::jsonb, COALESCE(?::timestamptz, now()))
                    ON CONFLICT (run_id, sequence) DO NOTHING
                    """,
                    UUID.randomUUID(),
                    runId,
                    event.sequence(),
                    event.eventType(),
                    json(event.payload()),
                    event.occurredAt());
        }
    }

    /** 轻量事件历史(SSE 无发布器时的补发真源;payload 结构化返回)。 */
    public List<Map<String, Object>> getRunEvents(UUID runId) {
        List<Map<String, Object>> events = jdbc.queryForList(
                """
                SELECT sequence, event_type, payload::text AS payload, occurred_at
                FROM touchstone.run_events WHERE run_id = ? ORDER BY sequence
                """,
                runId);
        events.forEach(row -> jsonbFields(row, "payload"));
        return events;
    }

    /** 运行配置补全(提前建行后,运行完成回写完整 modelConfig)。 */
    public void updateModelConfig(UUID runId, JsonNode modelConfig) {
        int updated = jdbc.update(
                """
                UPDATE touchstone.agent_runs SET model_config = ?::jsonb WHERE id = ?
                """,
                jsonOrEmpty(modelConfig),
                runId);
        if (updated == 0) {
            throw new IllegalArgumentException("unknown run_id: " + runId);
        }
    }

    /** 引擎重启后清理本批次的孤儿运行行(执行前建行但未达终态)。 */
    public int failStaleRuns(UUID batchId) {
        return jdbc.update(
                """
                UPDATE touchstone.agent_runs
                SET status = 'FAILED', error_category = 'PROCESS_RESTART',
                    error_message = '引擎重启:运行中断,未达到终态', completed_at = now()
                WHERE batch_id = ? AND status = 'CREATED'
                """,
                batchId);
    }

    /**
     * 批次级工具调用检索(可观测性设计 §10 阶段三:按 Tool/状态/审计码/参数字段)。
     * 返回 facets(下拉选项)、results(结构化行)、storageBytes(批次遥测字节合计);
     * 参数字段检索用 jsonb_exists(键存在)与 arguments->>(键取值),避免与占位符冲突。
     */
    public Map<String, Object> searchBatchToolCalls(
            UUID batchId, String tool, String status, String auditCode,
            String argumentKey, String argumentValue, int limit) {
        int safeLimit = Math.max(1, Math.min(limit <= 0 ? 200 : limit, 500));
        StringBuilder where = new StringBuilder(" ar.batch_id = ? ");
        List<Object> params = new ArrayList<>();
        params.add(batchId);
        if (tool != null && !tool.isBlank()) {
            where.append(" AND tc.tool_name = ? ");
            params.add(tool);
        }
        if (status != null && !status.isBlank()) {
            where.append(" AND tc.status = ? ");
            params.add(status);
        }
        if (auditCode != null && !auditCode.isBlank()) {
            where.append(" AND tc.audit_code = ? ");
            params.add(auditCode);
        }
        if (argumentKey != null && !argumentKey.isBlank()) {
            where.append(" AND jsonb_exists(tc.arguments, ?) ");
            params.add(argumentKey);
            if (argumentValue != null && !argumentValue.isBlank()) {
                where.append(" AND tc.arguments ->> ? = ? ");
                params.add(argumentKey);
                params.add(argumentValue);
            }
        }

        List<Map<String, Object>> results = jdbc.queryForList(
                """
                SELECT tc.run_id, tc.sequence, tc.tool_name, tc.status, tc.audit_code,
                       tc.fixture_hit, tc.duration_ms, tc.arguments::text AS arguments,
                       tc.error_category, ar.variant_id,
                       COALESCE(ar.model_config ->> 'variantLabel', ar.variant_id) AS variant_label
                FROM touchstone.tool_calls tc
                JOIN touchstone.agent_runs ar ON ar.id = tc.run_id
                WHERE """ + where + """
                ORDER BY ar.created_at DESC, tc.run_id, tc.sequence
                LIMIT ?
                """,
                params.stream().toArray());
        results.forEach(row -> jsonbFields(row, "arguments"));

        List<String> tools = jdbc.queryForList(
                """
                SELECT DISTINCT tc.tool_name FROM touchstone.tool_calls tc
                JOIN touchstone.agent_runs ar ON ar.id = tc.run_id
                WHERE ar.batch_id = ? ORDER BY tc.tool_name
                """,
                String.class, batchId);
        List<String> codes = jdbc.queryForList(
                """
                SELECT DISTINCT tc.audit_code FROM touchstone.tool_calls tc
                JOIN touchstone.agent_runs ar ON ar.id = tc.run_id
                WHERE ar.batch_id = ? AND tc.audit_code IS NOT NULL ORDER BY tc.audit_code
                """,
                String.class, batchId);
        List<String> argumentKeys = jdbc.queryForList(
                """
                SELECT DISTINCT key FROM (
                    SELECT jsonb_object_keys(tc.arguments) AS key
                    FROM touchstone.tool_calls tc
                    JOIN touchstone.agent_runs ar ON ar.id = tc.run_id
                    WHERE ar.batch_id = ?
                ) keys ORDER BY key
                """,
                String.class, batchId);
        Long storageBytes = jdbc.queryForObject(
                """
                SELECT COALESCE(SUM(m.telemetry_bytes), 0) FROM touchstone.run_measurements m
                JOIN touchstone.agent_runs ar ON ar.id = m.run_id
                WHERE ar.batch_id = ?
                """,
                Long.class, batchId);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("facets", Map.of(
                "tools", tools,
                "auditCodes", codes,
                "argumentKeys", argumentKeys));
        payload.put("results", results);
        payload.put("storageBytes", storageBytes == null ? 0L : storageBytes);
        payload.put("truncated", results.size() >= safeLimit);
        return payload;
    }

    @Transactional
    public void saveModelCalls(UUID runId, SaveModelCallsRequest request) {
        for (ModelCallInput call : request.calls()) {
            UUID callId = UUID.randomUUID();
            jdbc.update(
                    """
                    INSERT INTO touchstone.model_calls
                        (id, run_id, sequence, purpose, model, request_hash, response_hash,
                         input_tokens, output_tokens, duration_ms, retry_count, status, error_category,
                         decision, request_snapshot_version, request_payload, tool_schemas,
                         requested_params, sent_params, unsupported_params, response_summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            NULLIF(?::jsonb, 'null'::jsonb), NULLIF(?::jsonb, 'null'::jsonb),
                            NULLIF(?::jsonb, 'null'::jsonb), NULLIF(?::jsonb, 'null'::jsonb),
                            NULLIF(?::jsonb, 'null'::jsonb), NULLIF(?::jsonb, 'null'::jsonb))
                    """,
                    callId,
                    runId,
                    call.sequence(),
                    call.purpose(),
                    call.model(),
                    call.requestHash(),
                    call.responseHash(),
                    call.inputTokens(),
                    call.outputTokens(),
                    call.durationMs(),
                    call.retryCount(),
                    call.status(),
                    call.errorCategory(),
                    call.decision(),
                    call.requestSnapshotVersion(),
                    jsonOrNull(call.requestPayload()),
                    jsonOrNull(call.toolSchemas()),
                    jsonOrNull(call.requestedParams()),
                    jsonOrNull(call.sentParams()),
                    jsonOrNull(call.unsupportedParams()),
                    jsonOrNull(call.responseSummary()));
            if (call.messages() == null) {
                continue;
            }
            for (ModelCallMessageInput message : call.messages()) {
                jdbc.update(
                        """
                        INSERT INTO touchstone.model_call_messages
                            (id, run_id, model_call_id, message_order, role, content,
                             content_ref, tokens, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        UUID.randomUUID(),
                        runId,
                        callId,
                        message.messageOrder(),
                        message.role(),
                        message.content(),
                        message.contentRef(),
                        message.tokens(),
                        message.contentHash());
            }
        }
    }

    @Transactional
    public void saveToolCalls(UUID runId, SaveToolCallsRequest request) {
        for (ToolCallInput call : request.calls()) {
            jdbc.update(
                    """
                    INSERT INTO touchstone.tool_calls
                        (id, run_id, model_call_id, sequence, tool_name, arguments, arguments_hash, status,
                         result_summary, result_ref, result_hash, source_time, duration_ms, audit_code,
                         fixture_hit, error_category, call_id, requested_event_sequence, completed_event_sequence)
                    VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?::jsonb, ?, ?, ?::timestamptz, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    UUID.randomUUID(),
                    runId,
                    resolveModelCallId(runId, call.modelCallSequence()),
                    call.sequence(),
                    call.toolName(),
                    json(call.arguments()),
                    call.argumentsHash(),
                    call.status(),
                    jsonOrEmpty(call.resultSummary()),
                    call.resultRef(),
                    call.resultHash(),
                    call.sourceTime(),
                    call.durationMs(),
                    call.auditCode(),
                    call.fixtureHit(),
                    call.errorCategory(),
                    call.callId(),
                    call.requestedEventSequence(),
                    call.completedEventSequence());
        }
    }

    /** tool_calls.model_call_id 外键解析:engine 按 (run_id, model_call sequence) 关联。 */
    private UUID resolveModelCallId(UUID runId, Integer modelCallSequence) {
        if (modelCallSequence == null) {
            return null;
        }
        List<UUID> ids = jdbc.queryForList(
                "SELECT id FROM touchstone.model_calls WHERE run_id = ? AND sequence = ?",
                UUID.class,
                runId,
                modelCallSequence);
        if (ids.isEmpty()) {
            throw new IllegalArgumentException(
                    "tool call references unknown model_call sequence %d for run %s".formatted(modelCallSequence, runId));
        }
        return ids.get(0);
    }

    @Transactional
    public void saveGuardrailChecks(UUID runId, SaveGuardrailChecksRequest request) {
        for (GuardrailCheckInput check : request.checks()) {
            jdbc.update(
                    """
                    INSERT INTO touchstone.guardrail_checks
                        (id, run_id, sequence, stage, decision, audit_code, rule_ids,
                         reasons, tool_name, tool_call_id, model_call_id, detail, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?, ?::jsonb, ?)
                    """,
                    UUID.randomUUID(),
                    runId,
                    check.sequence(),
                    check.stage(),
                    check.decision(),
                    check.auditCode(),
                    jsonOr(check.ruleIds(), "[]"),
                    jsonOr(check.reasons(), "[]"),
                    check.toolName(),
                    resolveToolCallId(runId, check.toolCallSequence()),
                    resolveModelCallId(runId, check.modelCallSequence()),
                    jsonOr(check.detail(), "{}"),
                    check.durationMs());
        }
    }

    /** guardrail_checks.tool_call_id 外键解析(同 model_call_id)。 */
    private UUID resolveToolCallId(UUID runId, Integer toolCallSequence) {
        if (toolCallSequence == null) {
            return null;
        }
        List<UUID> ids = jdbc.queryForList(
                "SELECT id FROM touchstone.tool_calls WHERE run_id = ? AND sequence = ?",
                UUID.class,
                runId,
                toolCallSequence);
        return ids.isEmpty() ? null : ids.get(0);
    }

    public void saveMeasurements(UUID runId, SaveMeasurementsRequest m) {
        jdbc.update(
                """
                INSERT INTO touchstone.run_measurements
                    (run_id, queue_ms, snapshot_ms, context_collect_ms, context_compress_ms,
                     tool_loading_ms, llm_ms, tool_ms, guardrail_ms, judgment_ms,
                     first_output_ms, total_duration_ms, prompt_tokens, cached_prompt_tokens,
                     completion_tokens, compression_input_tokens, compression_output_tokens,
                     telemetry_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    queue_ms = EXCLUDED.queue_ms,
                    snapshot_ms = EXCLUDED.snapshot_ms,
                    context_collect_ms = EXCLUDED.context_collect_ms,
                    context_compress_ms = EXCLUDED.context_compress_ms,
                    tool_loading_ms = EXCLUDED.tool_loading_ms,
                    llm_ms = EXCLUDED.llm_ms,
                    tool_ms = EXCLUDED.tool_ms,
                    guardrail_ms = EXCLUDED.guardrail_ms,
                    judgment_ms = EXCLUDED.judgment_ms,
                    first_output_ms = EXCLUDED.first_output_ms,
                    total_duration_ms = EXCLUDED.total_duration_ms,
                    prompt_tokens = EXCLUDED.prompt_tokens,
                    cached_prompt_tokens = EXCLUDED.cached_prompt_tokens,
                    completion_tokens = EXCLUDED.completion_tokens,
                    compression_input_tokens = EXCLUDED.compression_input_tokens,
                    compression_output_tokens = EXCLUDED.compression_output_tokens,
                    telemetry_bytes = EXCLUDED.telemetry_bytes
                """,
                runId, m.queueMs(), m.snapshotMs(), m.contextCollectMs(), m.contextCompressMs(),
                m.toolLoadingMs(), m.llmMs(), m.toolMs(), m.guardrailMs(), m.judgmentMs(),
                m.firstOutputMs(), m.totalDurationMs(), m.promptTokens(), m.cachedPromptTokens(),
                m.completionTokens(), m.compressionInputTokens(), m.compressionOutputTokens(),
                m.telemetryBytes());
    }

    public void saveArtifact(UUID runId, SaveArtifactRequest request) {
        jdbc.update(
                """
                INSERT INTO touchstone.run_artifacts
                    (id, run_id, artifact_type, storage_ref, content_hash, public)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, artifact_type) DO UPDATE SET
                    storage_ref = EXCLUDED.storage_ref,
                    content_hash = EXCLUDED.content_hash,
                    public = EXCLUDED.public
                """,
                UUID.randomUUID(),
                runId,
                request.artifactType(),
                request.storageRef(),
                request.contentHash(),
                request.publicArtifact());
    }

    public void saveEvaluation(UUID runId, SaveEvaluationRequest request) {
        jdbc.update(
                """
                INSERT INTO touchstone.evaluation_results
                    (id, run_id, evaluator_version, valid_run, status, checks, metrics)
                VALUES (?, ?, ?, ?, ?, ?::jsonb, ?::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET
                    evaluator_version = EXCLUDED.evaluator_version,
                    valid_run = EXCLUDED.valid_run,
                    status = EXCLUDED.status,
                    checks = EXCLUDED.checks,
                    metrics = EXCLUDED.metrics,
                    created_at = now()
                """,
                UUID.randomUUID(),
                runId,
                request.evaluatorVersion(),
                request.validRun(),
                request.status(),
                json(request.checks()),
                jsonOrEmpty(request.metrics()));
    }

    public void complete(UUID runId, CompleteRunRequest request) {
        int updated = jdbc.update(
                """
                UPDATE touchstone.agent_runs
                SET status = ?, output = ?::jsonb, error_category = ?,
                    error_message = ?, completed_at = now()
                WHERE id = ?
                """,
                request.status(),
                jsonOrEmpty(request.output()),
                request.errorCategory(),
                request.errorMessage(),
                runId);
        if (updated == 0) {
            throw new IllegalArgumentException("unknown run_id: " + runId);
        }
    }

    public Map<String, Object> getRun(UUID runId) {
        Map<String, Object> run = new LinkedHashMap<>(jdbc.queryForMap(
                """
                SELECT id, batch_id, case_id, case_version, variant_id, snapshot_id,
                       agent_mode, context_strategy, model, model_config, git_commit,
                       status, output, error_category, error_message,
                       created_at, completed_at
                FROM touchstone.agent_runs WHERE id = ?
                """,
                runId));
        // JSONB 以结构化节点返回(可观测性设计 §7.1:不让前端再次 JSON.parse)
        jsonbFields(run, "model_config", "output");
        List<Map<String, Object>> builds = jdbc.queryForList(
                """
                SELECT id, strategy, tokenizer_version, compression_version,
                       token_budget, original_tokens, working_tokens, duration_ms,
                       required_retained, budget_fit, references_valid,
                       instruction_isolated, status, error_code, created_at
                FROM touchstone.context_builds
                WHERE run_id = ? ORDER BY created_at
                """,
                runId);
        run.put("contextBuilds", builds);
        return run;
    }

    /** 运行详情:run + 全局事件序号交织的 timeline + 各分表明细(可观测性设计 §7.1)。 */
    public Map<String, Object> getRunDetail(UUID runId) {
        Map<String, Object> run = getRun(runId);
        List<Map<String, Object>> events = jdbc.queryForList(
                """
                SELECT sequence, event_type, payload::text AS payload, occurred_at
                FROM touchstone.run_events WHERE run_id = ? ORDER BY sequence
                """,
                runId);
        events.forEach(row -> jsonbFields(row, "payload"));
        List<Map<String, Object>> modelCalls = jdbc.queryForList(
                """
                SELECT id, sequence, purpose, model, request_hash, response_hash,
                       input_tokens, output_tokens, duration_ms, retry_count,
                       status, error_category, decision, request_snapshot_version,
                       request_payload::text AS request_payload,
                       tool_schemas::text AS tool_schemas,
                       requested_params::text AS requested_params,
                       sent_params::text AS sent_params,
                       unsupported_params::text AS unsupported_params,
                       response_summary::text AS response_summary
                FROM touchstone.model_calls WHERE run_id = ? ORDER BY sequence
                """,
                runId);
        for (Map<String, Object> call : modelCalls) {
            jsonbFields(
                    call,
                    "request_payload",
                    "tool_schemas",
                    "requested_params",
                    "sent_params",
                    "unsupported_params",
                    "response_summary");
            call.put("messages", jdbc.queryForList(
                    """
                    SELECT message_order, role, content, content_ref, tokens, content_hash
                    FROM touchstone.model_call_messages
                    WHERE model_call_id = ? ORDER BY message_order
                    """,
                    call.get("id")));
        }
        List<Map<String, Object>> toolCalls = jdbc.queryForList(
                """
                SELECT sequence, tool_name, arguments::text AS arguments, arguments_hash,
                       status, result_summary::text AS result_summary, result_ref, result_hash,
                       source_time, duration_ms, audit_code, fixture_hit, error_category,
                       call_id, model_call_id, requested_event_sequence, completed_event_sequence
                FROM touchstone.tool_calls WHERE run_id = ? ORDER BY sequence
                """,
                runId);
        toolCalls.forEach(row -> jsonbFields(row, "arguments", "result_summary"));
        List<Map<String, Object>> guardrailChecks = jdbc.queryForList(
                """
                SELECT sequence, stage, decision, audit_code, rule_ids::text AS rule_ids,
                       reasons::text AS reasons, tool_name, tool_call_id, model_call_id,
                       detail::text AS detail, duration_ms
                FROM touchstone.guardrail_checks WHERE run_id = ? ORDER BY sequence
                """,
                runId);
        guardrailChecks.forEach(row -> jsonbFields(row, "rule_ids", "reasons", "detail"));
        List<Map<String, Object>> measurements = jdbc.queryForList(
                """
                SELECT queue_ms, snapshot_ms, context_collect_ms, context_compress_ms,
                       tool_loading_ms, llm_ms, tool_ms, guardrail_ms, judgment_ms,
                       first_output_ms, total_duration_ms, prompt_tokens,
                       cached_prompt_tokens, completion_tokens,
                       compression_input_tokens, compression_output_tokens, telemetry_bytes
                FROM touchstone.run_measurements WHERE run_id = ?
                """,
                runId);
        List<Map<String, Object>> artifacts = jdbc.queryForList(
                """
                SELECT artifact_type, storage_ref, content_hash, "public", created_at
                FROM touchstone.run_artifacts WHERE run_id = ?
                """,
                runId);
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("run", run);
        detail.put("timeline", buildTimeline(events, modelCalls, toolCalls, guardrailChecks));
        detail.put("events", events);
        detail.put("modelCalls", modelCalls);
        detail.put("toolCalls", toolCalls);
        detail.put("guardrailChecks", guardrailChecks);
        detail.put("measurements", measurements);
        detail.put("artifacts", artifacts);
        return detail;
    }

    /**
     * 时间线:以 run_events.sequence(运行内全局顺序真源,设计 §6.3)为主干,
     * 把 model.completed/tool.completed/guardrail.completed 事件与对应明细行
     * 关联展开;model.requested 作为「等待模型」锚点保留载荷。
     */
    private List<Map<String, Object>> buildTimeline(
            List<Map<String, Object>> events,
            List<Map<String, Object>> modelCalls,
            List<Map<String, Object>> toolCalls,
            List<Map<String, Object>> guardrailChecks) {
        Map<Integer, Map<String, Object>> modelBySequence = bySequence(modelCalls);
        Map<Integer, Map<String, Object>> toolBySequence = bySequence(toolCalls);
        Map<Integer, Map<String, Object>> guardrailBySequence = bySequence(guardrailChecks);
        List<Map<String, Object>> timeline = new ArrayList<>();
        for (Map<String, Object> event : events) {
            Object rawSequence = event.get("sequence");
            if (!(rawSequence instanceof Number number)) {
                continue;
            }
            String eventType = String.valueOf(event.get("eventType"));
            @SuppressWarnings("unchecked")
            Map<String, Object> payload =
                    event.get("payload") instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of();
            Integer detailSequence = intValue(payload.get("sequence"));
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("sequence", number.intValue());
            entry.put("eventType", eventType);
            switch (eventType) {
                case "model.completed" -> {
                    entry.put("type", "model");
                    Map<String, Object> modelCall = detailSequence == null ? null : modelBySequence.get(detailSequence);
                    if (modelCall != null) {
                        entry.put("modelCall", modelCall);
                    } else {
                        entry.put("payload", payload);
                    }
                }
                case "model.requested" -> {
                    entry.put("type", "model");
                    entry.put("payload", payload);
                }
                case "tool.completed" -> {
                    entry.put("type", "tool");
                    Map<String, Object> toolCall = detailSequence == null ? null : toolBySequence.get(detailSequence);
                    if (toolCall != null) {
                        entry.put("toolCall", toolCall);
                    } else {
                        entry.put("payload", payload);
                    }
                }
                case "guardrail.completed" -> {
                    entry.put("type", "guardrail");
                    Map<String, Object> check =
                            detailSequence == null ? null : guardrailBySequence.get(detailSequence);
                    if (check != null) {
                        entry.put("guardrailCheck", check);
                    } else {
                        entry.put("payload", payload);
                    }
                }
                default -> {
                    entry.put("type", "event");
                    entry.put("payload", payload);
                }
            }
            timeline.add(entry);
        }
        return timeline;
    }

    private Map<Integer, Map<String, Object>> bySequence(List<Map<String, Object>> rows) {
        Map<Integer, Map<String, Object>> index = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            if (row.get("sequence") instanceof Number number) {
                index.put(number.intValue(), row);
            }
        }
        return index;
    }

    private Integer intValue(Object value) {
        return value instanceof Number number ? number.intValue() : null;
    }

    private String json(JsonNode node) {
        try {
            return objectMapper.writeValueAsString(node);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("payload is not valid JSON", exception);
        }
    }

    private String jsonOrEmpty(JsonNode node) {
        return node == null ? "{}" : json(node);
    }

    private String jsonOrNull(JsonNode node) {
        return node == null ? "null" : json(node);
    }

    private String jsonOr(JsonNode node, String fallback) {
        return node == null ? fallback : json(node);
    }

    /** 库内 jsonb(::text 读出)→ 结构化 JSON 节点;NULL/空值返回 null 节点。 */
    private JsonNode jsonb(Object stored) {
        if (stored == null) {
            return objectMapper.nullNode();
        }
        try {
            return objectMapper.readTree(stored.toString());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored jsonb is not valid JSON", exception);
        }
    }

    private void jsonbFields(Map<String, Object> row, String... keys) {
        for (String key : keys) {
            row.put(key, jsonb(row.get(key)));
        }
    }
}
