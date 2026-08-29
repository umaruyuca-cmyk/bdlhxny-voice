package com.bdlh.touchstone.data.api;

import static com.bdlh.touchstone.data.domain.RunPayloads.*;

import com.bdlh.touchstone.data.repository.RunRepository;
import jakarta.validation.Valid;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/internal/v1")
public class RunController {
    private final RunRepository runs;

    public RunController(RunRepository runs) {
        this.runs = runs;
    }

    @PostMapping("/batches")
    public Map<String, UUID> createBatch(@Valid @RequestBody CreateBatchRequest request) {
        return Map.of("batchId", runs.createBatch(request));
    }

    @PostMapping("/runs")
    public Map<String, UUID> createRun(@Valid @RequestBody CreateRunRequest request) {
        return Map.of("runId", runs.createRun(request));
    }

    @PostMapping("/batches/{batchId}/complete")
    public ResponseEntity<Void> completeBatch(
            @PathVariable UUID batchId,
            @Valid @RequestBody CompleteBatchRequest request) {
        runs.completeBatch(batchId, request);
        return ResponseEntity.accepted().build();
    }

    /** 批次执行报告写入(engine 完成时调用;报告读取的第一来源)。 */
    @PostMapping("/batches/{batchId}/report")
    public ResponseEntity<Void> saveBatchReport(
            @PathVariable UUID batchId,
            @Valid @RequestBody SaveBatchReportRequest request) {
        runs.saveBatchReport(batchId, request);
        return ResponseEntity.accepted().build();
    }

    /** 批次执行报告读取;无报告(未完成/历史批次)返回 404,由调用方回退本地工件。 */
    @GetMapping("/batches/{batchId}/report")
    public ResponseEntity<Map<String, Object>> getBatchReport(@PathVariable UUID batchId) {
        com.fasterxml.jackson.databind.JsonNode report = runs.getBatchReport(batchId);
        if (report == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(Map.of("report", report));
    }

    @GetMapping("/batches")
    public Map<String, Object> listBatches(
            @RequestParam(defaultValue = "20") int limit,
            @RequestParam(required = false) UUID cursor) {
        // 上限 100:所有者批次列表分页保护;cursor = 上一页最后一条批次 id
        return runs.listBatches(Math.min(Math.max(limit, 1), 100), cursor);
    }

    @GetMapping("/batches/{batchId}")
    public ResponseEntity<Map<String, Object>> getBatch(@PathVariable UUID batchId) {
        try {
            return ResponseEntity.ok(runs.getBatch(batchId));
        } catch (org.springframework.dao.EmptyResultDataAccessException exception) {
            return ResponseEntity.notFound().build();
        }
    }

    @GetMapping("/runs/{runId}")
    public ResponseEntity<Map<String, Object>> getRun(@PathVariable UUID runId) {
        try {
            return ResponseEntity.ok(runs.getRun(runId));
        } catch (org.springframework.dao.EmptyResultDataAccessException exception) {
            return ResponseEntity.notFound().build();
        }
    }

    @PostMapping("/runs/{runId}/context-builds")
    public Map<String, UUID> saveContextBuild(
            @PathVariable UUID runId,
            @Valid @RequestBody SaveContextBuildRequest request) {
        return Map.of("contextBuildId", runs.saveContextBuild(runId, request));
    }

    @PostMapping("/runs/{runId}/events")
    public ResponseEntity<Void> saveEvents(
            @PathVariable UUID runId,
            @Valid @RequestBody SaveEventsRequest request) {
        runs.saveEvents(runId, request);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/runs/{runId}/model-calls")
    public ResponseEntity<Void> saveModelCalls(
            @PathVariable UUID runId,
            @Valid @RequestBody SaveModelCallsRequest request) {
        runs.saveModelCalls(runId, request);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/runs/{runId}/tool-calls")
    public ResponseEntity<Void> saveToolCalls(
            @PathVariable UUID runId,
            @Valid @RequestBody SaveToolCallsRequest request) {
        runs.saveToolCalls(runId, request);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/runs/{runId}/guardrail-checks")
    public ResponseEntity<Void> saveGuardrailChecks(
            @PathVariable UUID runId,
            @Valid @RequestBody SaveGuardrailChecksRequest request) {
        runs.saveGuardrailChecks(runId, request);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/runs/{runId}/measurements")
    public ResponseEntity<Void> saveMeasurements(
            @PathVariable UUID runId,
            @Valid @RequestBody SaveMeasurementsRequest request) {
        runs.saveMeasurements(runId, request);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/runs/{runId}/artifacts")
    public ResponseEntity<Void> saveArtifact(
            @PathVariable UUID runId,
            @Valid @RequestBody SaveArtifactRequest request) {
        runs.saveArtifact(runId, request);
        return ResponseEntity.accepted().build();
    }

    @GetMapping("/runs/{runId}/detail")
    public ResponseEntity<Map<String, Object>> getRunDetail(@PathVariable UUID runId) {
        try {
            return ResponseEntity.ok(runs.getRunDetail(runId));
        } catch (org.springframework.dao.EmptyResultDataAccessException exception) {
            return ResponseEntity.notFound().build();
        }
    }

    @PostMapping("/runs/{runId}/evaluation")
    public ResponseEntity<Void> saveEvaluation(
            @PathVariable UUID runId,
            @Valid @RequestBody SaveEvaluationRequest request) {
        runs.saveEvaluation(runId, request);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/runs/{runId}/complete")
    public ResponseEntity<Void> complete(
            @PathVariable UUID runId,
            @Valid @RequestBody CompleteRunRequest request) {
        runs.complete(runId, request);
        return ResponseEntity.accepted().build();
    }

    /** 轻量事件历史(SSE 无发布器时的补发真源)。 */
    @GetMapping("/runs/{runId}/events")
    public ResponseEntity<List<Map<String, Object>>> getRunEvents(@PathVariable UUID runId) {
        return ResponseEntity.ok(runs.getRunEvents(runId));
    }

    /** 运行配置补全(提前建行后,运行完成回写完整 modelConfig)。 */
    @PostMapping("/runs/{runId}/model-config")
    public ResponseEntity<Void> updateModelConfig(
            @PathVariable UUID runId,
            @Valid @RequestBody UpdateModelConfigRequest request) {
        runs.updateModelConfig(runId, request.modelConfig());
        return ResponseEntity.accepted().build();
    }

    /** 引擎重启后清理本批次的孤儿运行行(执行前建行但未达终态)。 */
    @PostMapping("/batches/{batchId}/fail-stale-runs")
    public ResponseEntity<Map<String, Object>> failStaleRuns(@PathVariable UUID batchId) {
        return ResponseEntity.ok(Map.of("failedRuns", runs.failStaleRuns(batchId)));
    }
}
