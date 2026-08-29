package com.bdlh.touchstone.data.repository;

import static com.bdlh.touchstone.data.domain.RunPayloads.*;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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
                    """,
                    UUID.randomUUID(),
                    runId,
                    event.sequence(),
                    event.eventType(),
                    json(event.payload()),
                    event.occurredAt());
        }
    }

    @Transactional
    public void saveModelCalls(UUID runId, SaveModelCallsRequest request) {
        for (ModelCallInput call : request.calls()) {
            UUID callId = UUID.randomUUID();
            jdbc.update(
                    """
                    INSERT INTO touchstone.model_calls
                        (id, run_id, sequence, purpose, model, request_hash, response_hash,
                         input_tokens, output_tokens, duration_ms, retry_count, status, error_category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    call.errorCategory());
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
                        (id, run_id, sequence, tool_name, arguments, arguments_hash, status,
                         result_summary, result_hash, source_time, duration_ms, audit_code,
                         fixture_hit, error_category)
                    VALUES (?, ?, ?, ?, ?::jsonb, ?, ?, ?::jsonb, ?, ?::timestamptz, ?, ?, ?, ?)
                    """,
                    UUID.randomUUID(),
                    runId,
                    call.sequence(),
                    call.toolName(),
                    json(call.arguments()),
                    call.argumentsHash(),
                    call.status(),
                    jsonOrEmpty(call.resultSummary()),
                    call.resultHash(),
                    call.sourceTime(),
                    call.durationMs(),
                    call.auditCode(),
                    call.fixtureHit(),
                    call.errorCategory());
        }
    }

    @Transactional
    public void saveGuardrailChecks(UUID runId, SaveGuardrailChecksRequest request) {
        for (GuardrailCheckInput check : request.checks()) {
            jdbc.update(
                    """
                    INSERT INTO touchstone.guardrail_checks
                        (id, run_id, sequence, stage, decision, audit_code, rule_ids,
                         reasons, tool_name, detail, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?::jsonb, ?)
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
                    jsonOr(check.detail(), "{}"),
                    check.durationMs());
        }
    }

    public void saveMeasurements(UUID runId, SaveMeasurementsRequest m) {
        jdbc.update(
                """
                INSERT INTO touchstone.run_measurements
                    (run_id, queue_ms, snapshot_ms, context_collect_ms, context_compress_ms,
                     tool_loading_ms, llm_ms, tool_ms, guardrail_ms, judgment_ms,
                     first_output_ms, total_duration_ms, prompt_tokens, cached_prompt_tokens,
                     completion_tokens, compression_input_tokens, compression_output_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    compression_output_tokens = EXCLUDED.compression_output_tokens
                """,
                runId, m.queueMs(), m.snapshotMs(), m.contextCollectMs(), m.contextCompressMs(),
                m.toolLoadingMs(), m.llmMs(), m.toolMs(), m.guardrailMs(), m.judgmentMs(),
                m.firstOutputMs(), m.totalDurationMs(), m.promptTokens(), m.cachedPromptTokens(),
                m.completionTokens(), m.compressionInputTokens(), m.compressionOutputTokens());
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

    /** /lab 运行详情:事件流 + 模型/工具/guardrail 明细 + 测量 + 工件登记。 */
    public Map<String, Object> getRunDetail(UUID runId) {
        Map<String, Object> run = getRun(runId);
        run.put("events", jdbc.queryForList(
                """
                SELECT sequence, event_type, payload::text AS payload, occurred_at
                FROM touchstone.run_events WHERE run_id = ? ORDER BY sequence
                """,
                runId));
        List<Map<String, Object>> calls = jdbc.queryForList(
                """
                SELECT id, sequence, purpose, model, request_hash, response_hash,
                       input_tokens, output_tokens, duration_ms, retry_count,
                       status, error_category
                FROM touchstone.model_calls WHERE run_id = ? ORDER BY sequence
                """,
                runId);
        for (Map<String, Object> call : calls) {
            call.put("messages", jdbc.queryForList(
                    """
                    SELECT message_order, role, content, content_ref, tokens, content_hash
                    FROM touchstone.model_call_messages
                    WHERE model_call_id = ? ORDER BY message_order
                    """,
                    call.get("id")));
        }
        run.put("modelCalls", calls);
        run.put("toolCalls", jdbc.queryForList(
                """
                SELECT sequence, tool_name, arguments::text AS arguments, arguments_hash,
                       status, result_summary::text AS result_summary, result_hash,
                       source_time, duration_ms, audit_code, fixture_hit, error_category
                FROM touchstone.tool_calls WHERE run_id = ? ORDER BY sequence
                """,
                runId));
        run.put("guardrailChecks", jdbc.queryForList(
                """
                SELECT sequence, stage, decision, audit_code, rule_ids::text AS rule_ids,
                       reasons::text AS reasons, tool_name, detail::text AS detail, duration_ms
                FROM touchstone.guardrail_checks WHERE run_id = ? ORDER BY sequence
                """,
                runId));
        run.put("measurements", jdbc.queryForList(
                """
                SELECT queue_ms, snapshot_ms, context_collect_ms, context_compress_ms,
                       tool_loading_ms, llm_ms, tool_ms, guardrail_ms, judgment_ms,
                       first_output_ms, total_duration_ms, prompt_tokens,
                       cached_prompt_tokens, completion_tokens,
                       compression_input_tokens, compression_output_tokens
                FROM touchstone.run_measurements WHERE run_id = ?
                """,
                runId));
        run.put("artifacts", jdbc.queryForList(
                """
                SELECT artifact_type, storage_ref, content_hash, "public", created_at
                FROM touchstone.run_artifacts WHERE run_id = ?
                """,
                runId));
        return run;
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
}
