package com.bdlh.runtime.api;

import com.bdlh.runtime.runtime.RuntimeDataDtos.AnalysisHistoryResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.ChatMessageRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.ChatSessionResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.EnsureSessionRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.PendingRunRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.RunLocationResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.RunProjectionResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.SaveHistoryRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.SaveRunProjectionRequest;
import com.bdlh.runtime.runtime.RuntimeDataDtos.UpsertRunRequest;
import com.bdlh.runtime.runtime.RuntimeDataService;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** 仅供受认证的 Orchestrator 调用的 Runtime Data 用例 API。 */
@Tag(name = "Runtime Data API", description = "Chat、Run Registry 与 Analysis History 的内部用例接口")
@RestController
@RequestMapping("/internal/v1/runtime")
public class RuntimeDataController {

    private final JavaDataAccessGuard accessGuard;
    private final RuntimeDataService runtimeDataService;

    public RuntimeDataController(
            JavaDataAccessGuard accessGuard,
            RuntimeDataService runtimeDataService) {
        this.accessGuard = accessGuard;
        this.runtimeDataService = runtimeDataService;
    }

    @PostMapping("/sessions")
    public ChatSessionResponse ensureSession(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @RequestBody(required = false) EnsureSessionRequest request) {
        return runtimeDataService.ensureSession(
                accessGuard.resolveUserId(requestedUserId),
                request == null ? null : request.requestedSessionId());
    }

    @GetMapping("/sessions")
    public List<ChatSessionResponse> listSessions(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @RequestParam(defaultValue = "20") int limit) {
        return runtimeDataService.listSessions(accessGuard.resolveUserId(requestedUserId), limit);
    }

    @GetMapping("/sessions/{sessionId}")
    public ChatSessionResponse getSession(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String sessionId) {
        return runtimeDataService.getSession(accessGuard.resolveUserId(requestedUserId), sessionId);
    }

    @PostMapping("/sessions/{sessionId}/messages")
    public ChatSessionResponse appendMessage(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String sessionId,
            @RequestBody ChatMessageRequest request) {
        return runtimeDataService.appendMessage(accessGuard.resolveUserId(requestedUserId), sessionId, request);
    }

    @PostMapping("/sessions/{sessionId}/prepare-regeneration")
    public ChatSessionResponse prepareRegeneration(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String sessionId) {
        return runtimeDataService.prepareRegeneration(accessGuard.resolveUserId(requestedUserId), sessionId);
    }

    @PutMapping("/sessions/{sessionId}/pending")
    public ChatSessionResponse setPending(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String sessionId,
            @RequestBody PendingRunRequest request) {
        return runtimeDataService.setPending(accessGuard.resolveUserId(requestedUserId), sessionId, request);
    }

    @DeleteMapping("/sessions/{sessionId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteSession(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String sessionId) {
        runtimeDataService.deleteSession(accessGuard.resolveUserId(requestedUserId), sessionId);
    }

    @PutMapping("/runs/{runId}")
    public RunLocationResponse upsertRun(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String runId,
            @RequestBody UpsertRunRequest request) {
        return runtimeDataService.upsertRun(accessGuard.resolveUserId(requestedUserId), runId, request);
    }

    @GetMapping("/runs/{runId}")
    public RunLocationResponse getRun(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String runId) {
        return runtimeDataService.getRun(accessGuard.resolveUserId(requestedUserId), runId);
    }

    @PutMapping("/runs/{runId}/projection")
    public RunProjectionResponse saveRunProjection(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String runId,
            @RequestBody SaveRunProjectionRequest request) {
        return runtimeDataService.saveRunProjection(
                accessGuard.resolveUserId(requestedUserId), runId, request);
    }

    @GetMapping("/runs/{runId}/projection")
    public RunProjectionResponse getRunProjection(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String runId) {
        return runtimeDataService.getRunProjection(accessGuard.resolveUserId(requestedUserId), runId);
    }

    @PutMapping("/history/{historyId}")
    public AnalysisHistoryResponse saveHistory(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String historyId,
            @RequestBody SaveHistoryRequest request) {
        return runtimeDataService.saveHistory(accessGuard.resolveUserId(requestedUserId), historyId, request);
    }

    @GetMapping("/history/{historyId}")
    public AnalysisHistoryResponse getHistory(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String historyId) {
        return runtimeDataService.getHistory(accessGuard.resolveUserId(requestedUserId), historyId);
    }

    @GetMapping("/history")
    public List<AnalysisHistoryResponse> listHistory(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @RequestParam(name = "thread_id") String threadId) {
        return runtimeDataService.listHistory(accessGuard.resolveUserId(requestedUserId), threadId);
    }
}
