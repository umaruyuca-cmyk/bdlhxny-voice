package com.bdlh.touchstone.data.api;

import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.CreateBuildRequest;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.SaveArtifactRequest;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.SaveMemorySegmentRequest;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.SaveSessionRequest;
import com.bdlh.touchstone.data.domain.ContextMemoryPayloads.UpdateBuildRequest;
import com.bdlh.touchstone.data.repository.ContextMemoryRepository;
import com.bdlh.touchstone.data.repository.ContextMemoryRepository.BuildConflict;
import jakarta.validation.Valid;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Engine 专用的上下文记忆数据接口；公网 API 不直接暴露。 */
@RestController
@RequestMapping("/internal/v1/context")
public class ContextMemoryController {
    private final ContextMemoryRepository context;

    public ContextMemoryController(ContextMemoryRepository context) {
        this.context = context;
    }

    @GetMapping("/sessions")
    public Map<String, Object> listSessions(@RequestParam UUID accountId) {
        return Map.of("sessions", context.listSessions(accountId));
    }

    @GetMapping("/sessions/{sessionId}")
    public ResponseEntity<Map<String, Object>> getSession(
            @PathVariable String sessionId,
            @RequestParam UUID accountId) {
        return context.findSession(accountId, sessionId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping("/sessions/{sessionId}/events")
    public Map<String, List<Map<String, Object>>> getEvents(
            @PathVariable String sessionId,
            @RequestParam UUID accountId) {
        return Map.of("events", context.listEvents(accountId, sessionId));
    }

    @PostMapping("/sessions")
    public ResponseEntity<Void> saveSession(@Valid @RequestBody SaveSessionRequest request) {
        context.saveSession(request);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/builds")
    public ResponseEntity<Map<String, Object>> createBuild(
            @Valid @RequestBody CreateBuildRequest request) {
        try {
            ContextMemoryRepository.BuildCreation result = context.createBuild(request);
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("buildId", result.buildId());
            payload.put("replay", result.replay());
            return ResponseEntity.status(result.replay() ? HttpStatus.OK : HttpStatus.ACCEPTED)
                    .body(payload);
        } catch (BuildConflict conflict) {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("errorCode", conflict.code());
            payload.put("activeBuildId", conflict.activeBuildId());
            return ResponseEntity.status(HttpStatus.CONFLICT).body(payload);
        }
    }

    @GetMapping("/builds/{buildId}")
    public ResponseEntity<Map<String, Object>> getBuild(
            @PathVariable UUID buildId,
            @RequestParam UUID accountId) {
        return context.findBuild(accountId, buildId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping("/sessions/{sessionId}/latest-build")
    public ResponseEntity<Map<String, Object>> getLatestBuild(
            @PathVariable String sessionId,
            @RequestParam UUID accountId) {
        return context.latestBuildForSession(accountId, sessionId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PutMapping("/builds/{buildId}")
    public ResponseEntity<Void> updateBuild(
            @PathVariable UUID buildId,
            @Valid @RequestBody UpdateBuildRequest request) {
        context.updateBuild(buildId, request);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/builds/{buildId}/artifact")
    public Map<String, UUID> saveArtifact(
            @PathVariable UUID buildId,
            @Valid @RequestBody SaveArtifactRequest request) {
        return Map.of("artifactId", context.saveArtifact(buildId, request));
    }

    @GetMapping("/builds/{buildId}/artifact")
    public ResponseEntity<Map<String, Object>> getArtifact(
            @PathVariable UUID buildId,
            @RequestParam UUID accountId) {
        return context.findArtifact(accountId, buildId)
                .map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @PostMapping("/sessions/{sessionId}/memory-segments")
    public Map<String, UUID> saveMemorySegment(
            @PathVariable String sessionId,
            @Valid @RequestBody SaveMemorySegmentRequest request) {
        return Map.of("segmentId", context.saveMemorySegment(sessionId, request));
    }

    @GetMapping("/sessions/{sessionId}/memory-segments")
    public Map<String, List<Map<String, Object>>> listMemorySegments(
            @PathVariable String sessionId,
            @RequestParam UUID accountId) {
        return Map.of("segments", context.listMemorySegments(accountId, sessionId));
    }
}
