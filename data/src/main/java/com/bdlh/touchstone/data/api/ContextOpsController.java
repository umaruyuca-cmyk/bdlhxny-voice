package com.bdlh.touchstone.data.api;

import static com.bdlh.touchstone.data.domain.ContextOpsPayloads.*;

import com.bdlh.touchstone.data.repository.ContextOpsRepository;
import com.bdlh.touchstone.data.repository.ContextOpsRepository.GrantConflict;
import jakarta.validation.Valid;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 上下文细粒度 RBAC 内部接口(Engine 专用):
 * - 授权管理:所有者创建/列出/撤销 ARTIFACT_READ 授权;
 * - 权限判定:活跃授权查询(build 精确或全局);
 * - 审计:写入与读取(复用 audit_log,只暴露 CONTEXT_ 前缀动作);
 * - 跨所有者构建元数据(运维脱敏视图原始行;内容裁剪在 Engine 完成)。
 */
@RestController
@RequestMapping("/internal/v1/context/ops")
public class ContextOpsController {
    private final ContextOpsRepository ops;

    public ContextOpsController(ContextOpsRepository ops) {
        this.ops = ops;
    }

    @PostMapping("/access-grants")
    public ResponseEntity<Map<String, Object>> createGrant(@Valid @RequestBody CreateGrantRequest request) {
        try {
            return ResponseEntity.status(HttpStatus.CREATED).body(ops.createGrant(request));
        } catch (GrantConflict exception) {
            throw ContextOpsRepository.conflict(exception);
        }
    }

    @GetMapping("/access-grants")
    public Map<String, Object> listGrants(@RequestParam UUID ownerAccountId) {
        return Map.of("grants", ops.listGrants(ownerAccountId));
    }

    @DeleteMapping("/access-grants/{grantId}")
    public ResponseEntity<Void> revokeGrant(
            @PathVariable UUID grantId,
            @RequestParam UUID ownerAccountId) {
        return ops.revokeGrant(ownerAccountId, grantId)
                ? ResponseEntity.noContent().build()
                : ResponseEntity.notFound().build();
    }

    @GetMapping("/access-grants/active")
    public Map<String, Object> hasActiveGrant(
            @RequestParam UUID ownerAccountId,
            @RequestParam UUID granteeAccountId,
            @RequestParam String buildId) {
        return Map.of("granted", ops.hasActiveGrant(ownerAccountId, granteeAccountId, buildId));
    }

    /** 被授权方视角:Engine 校验跨所有者下载权限(无需指明 owner)。 */
    @GetMapping("/access-grants/active-for-grantee")
    public Map<String, Object> hasActiveGrantForGrantee(
            @RequestParam UUID granteeAccountId,
            @RequestParam String buildId) {
        return Map.of("granted", ops.hasActiveGrantForGrantee(granteeAccountId, buildId));
    }

    /** 跨所有者工件读取(Engine 在授权放行后调用;内部接口)。 */
    @GetMapping("/builds/{buildId}/artifact")
    public ResponseEntity<Map<String, Object>> getArtifactCrossOwner(@PathVariable String buildId) {
        return ops.findArtifactCrossOwner(buildId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping("/audit")
    public ResponseEntity<Void> writeAudit(@Valid @RequestBody WriteAuditRequest request) {
        ops.writeAudit(request);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/audit")
    public Map<String, Object> listAudit(
            @RequestParam(required = false) UUID accountId,
            @RequestParam(defaultValue = "50") int limit) {
        return Map.of("events", ops.listAudit(accountId, limit));
    }

    @GetMapping("/builds")
    public Map<String, Object> listBuilds(
            @RequestParam(defaultValue = "50") int limit,
            @RequestParam(defaultValue = "0") int cursor) {
        return ops.listBuildsCrossOwner(limit, cursor);
    }

    // ── P2 定时分析(Engine 分析任务专用) ──

    /** 跨所有者最近可用摘要段采样源(含来源正文,供评审模型对比)。 */
    @GetMapping("/segments/recent")
    public Map<String, Object> listRecentSegments(@RequestParam(defaultValue = "5") int limit) {
        return Map.of("segments", ops.listRecentSegmentsCrossOwner(limit));
    }

    @PostMapping("/segment-quality-checks")
    public ResponseEntity<Map<String, Object>> saveQualityCheck(
            @Valid @RequestBody SaveQualityCheckRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(ops.saveQualityCheck(request));
    }

    @GetMapping("/segment-quality-checks")
    public Map<String, Object> listQualityChecks(
            @RequestParam(required = false) UUID accountId,
            @RequestParam(required = false) String sessionId,
            @RequestParam(defaultValue = "50") int limit) {
        return Map.of("checks", ops.listQualityChecks(accountId, sessionId, limit));
    }

    @PostMapping("/analysis-runs")
    public ResponseEntity<Map<String, Object>> startAnalysisRun(
            @Valid @RequestBody StartAnalysisRunRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(Map.of("runId", ops.startAnalysisRun(request.triggerSource()), "status", "RUNNING"));
    }

    @PutMapping("/analysis-runs/{runId}")
    public ResponseEntity<Void> finishAnalysisRun(
            @PathVariable UUID runId,
            @Valid @RequestBody FinishAnalysisRunRequest request) {
        return ops.finishAnalysisRun(runId, request)
                ? ResponseEntity.noContent().build()
                : ResponseEntity.notFound().build();
    }

    @GetMapping("/analysis-runs")
    public Map<String, Object> listAnalysisRuns(@RequestParam(defaultValue = "5") int limit) {
        return Map.of("runs", ops.listAnalysisRuns(limit));
    }
}
