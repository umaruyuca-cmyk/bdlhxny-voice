package com.bdlh.touchstone.data.api;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.bdlh.touchstone.data.repository.ContextMemoryRepository;
import com.bdlh.touchstone.data.repository.ContextMemoryRepository.BuildConflict;
import com.bdlh.touchstone.data.repository.ContextMemoryRepository.BuildCreation;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class ContextMemoryControllerTest {
    private static final UUID ACCOUNT_ID = UUID.fromString("10000000-0000-0000-0000-000000000001");
    private ContextMemoryRepository repository;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        repository = Mockito.mock(ContextMemoryRepository.class);
        mvc = MockMvcBuilders.standaloneSetup(new ContextMemoryController(repository)).build();
    }

    @Test
    void listsOnlyOwnerSessions() throws Exception {
        when(repository.listSessions(ACCOUNT_ID))
                .thenReturn(List.of(Map.of(
                        "sessionId", "session-1",
                        "title", "生产会话",
                        "sourceType", "PRODUCTION_DB")));

        mvc.perform(get("/internal/v1/context/sessions").param("accountId", ACCOUNT_ID.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sessions[0].sessionId").value("session-1"))
                .andExpect(jsonPath("$.sessions[0].sourceType").value("PRODUCTION_DB"));
    }

    @Test
    void returnsSessionWithEventsOrNotFound() throws Exception {
        when(repository.findSession(ACCOUNT_ID, "session-1"))
                .thenReturn(Optional.of(Map.of(
                        "sessionId", "session-1",
                        "events", List.of(Map.of("eventId", "event-1")))))
                .thenReturn(Optional.empty());

        mvc.perform(get("/internal/v1/context/sessions/session-1")
                        .param("accountId", ACCOUNT_ID.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.events[0].eventId").value("event-1"));
        mvc.perform(get("/internal/v1/context/sessions/session-1")
                        .param("accountId", ACCOUNT_ID.toString()))
                .andExpect(status().isNotFound());
    }

    @Test
    void createsAndReplaysBuildsWithDifferentHttpStatuses() throws Exception {
        UUID buildId = UUID.fromString("20000000-0000-0000-0000-000000000001");
        when(repository.createBuild(any()))
                .thenReturn(new BuildCreation(buildId, false))
                .thenReturn(new BuildCreation(buildId, true));
        String body = """
                {"accountId":"10000000-0000-0000-0000-000000000001",
                 "sessionId":"session-1","currentRequestEventId":"event-9",
                 "algorithmVersion":"budgeted-hybrid-v1","idempotencyKey":"idem-0001",
                 "requestHash":"sha256:request","configSnapshot":{}}
                """;

        mvc.perform(post("/internal/v1/context/builds")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.buildId").value(buildId.toString()))
                .andExpect(jsonPath("$.replay").value(false));
        mvc.perform(post("/internal/v1/context/builds")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.replay").value(true));
    }

    @Test
    void returnsStableConflictPayloadForActiveBuild() throws Exception {
        UUID buildId = UUID.fromString("20000000-0000-0000-0000-000000000002");
        when(repository.createBuild(any())).thenThrow(new BuildConflict("ACTIVE_BUILD_EXISTS", buildId));

        mvc.perform(post("/internal/v1/context/builds")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"accountId":"10000000-0000-0000-0000-000000000001",
                                 "sessionId":"session-1","currentRequestEventId":"event-9",
                                 "algorithmVersion":"budgeted-hybrid-v1","idempotencyKey":"idem-0002",
                                 "requestHash":"sha256:request","configSnapshot":{}}
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.errorCode").value("ACTIVE_BUILD_EXISTS"))
                .andExpect(jsonPath("$.activeBuildId").value(buildId.toString()));
    }

    @Test
    void rejectsSessionWithoutEventsBeforeRepositoryCall() throws Exception {
        mvc.perform(post("/internal/v1/context/sessions")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"accountId":"10000000-0000-0000-0000-000000000001",
                                 "sessionId":"session-1","title":"空会话",
                                 "sourceType":"PRODUCTION_DB","sourceHash":"sha256:source",
                                 "sourceVersion":1,"status":"ACTIVE","events":[]}
                                """))
                .andExpect(status().isBadRequest());
    }

    @Test
    void listsMemorySegmentsOnlyForRequestingOwner() throws Exception {
        when(repository.listMemorySegments(ACCOUNT_ID, "session-1"))
                .thenReturn(List.of(Map.of(
                        "segmentId", UUID.fromString("40000000-0000-0000-0000-000000000001"),
                        "startEventId", "event-1",
                        "endEventId", "event-2",
                        "sourceHash", "sha256:segment",
                        "status", "FROZEN")));

        mvc.perform(get("/internal/v1/context/sessions/session-1/memory-segments")
                        .param("accountId", ACCOUNT_ID.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.segments[0].segmentId").value("40000000-0000-0000-0000-000000000001"))
                .andExpect(jsonPath("$.segments[0].status").value("FROZEN"));
        // 所有者隔离:仓库查询必须绑定请求的 accountId,不能读取其他账号的 Segment
        verify(repository).listMemorySegments(ACCOUNT_ID, "session-1");
    }

    @Test
    void returnsLatestBuildForSessionOrNotFound() throws Exception {
        UUID buildId = UUID.fromString("20000000-0000-0000-0000-000000000004");
        when(repository.latestBuildForSession(ACCOUNT_ID, "session-1"))
                .thenReturn(Optional.of(Map.of(
                        "buildId", buildId,
                        "status", "COMPLETED",
                        "currentPhase", "COMPLETED")))
                .thenReturn(Optional.empty());

        mvc.perform(get("/internal/v1/context/sessions/session-1/latest-build")
                        .param("accountId", ACCOUNT_ID.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.buildId").value(buildId.toString()))
                .andExpect(jsonPath("$.status").value("COMPLETED"));
        mvc.perform(get("/internal/v1/context/sessions/session-1/latest-build")
                        .param("accountId", ACCOUNT_ID.toString()))
                .andExpect(status().isNotFound());
    }

    @Test
    void savesMemorySegmentAndReturnsStableId() throws Exception {
        UUID segmentId = UUID.fromString("40000000-0000-0000-0000-000000000002");
        when(repository.saveMemorySegment(
                        eq("session-1"), argThat(request -> request != null
                                && request.accountId().equals(ACCOUNT_ID)
                                && request.startEventId().equals("event-1")
                                && request.promptVersion().equals("turn-summary-v1"))))
                .thenReturn(segmentId);

        mvc.perform(post("/internal/v1/context/sessions/session-1/memory-segments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"accountId":"10000000-0000-0000-0000-000000000001",
                                 "startEventId":"event-1","endEventId":"event-2",
                                 "sourceEventIds":["event-1","event-2"],
                                 "sourceHash":"sha256:segment","sourceTokens":120,
                                 "summaryContent":"轮摘要","summaryTokens":40,
                                 "status":"FROZEN","promptVersion":"turn-summary-v1",
                                 "algorithmVersion":"turn-segment-v1",
                                 "generationMode":"LLM"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.segmentId").value(segmentId.toString()));
    }

    @Test
    void savesAndReturnsArtifactWithSegmentSnapshot() throws Exception {
        UUID buildId = UUID.fromString("20000000-0000-0000-0000-000000000003");
        UUID artifactId = UUID.fromString("30000000-0000-0000-0000-000000000002");
        when(repository.saveArtifact(eq(buildId), argThat(request -> request != null
                        && request.accountId().equals(ACCOUNT_ID)
                        && request.memorySegments() != null
                        && request.memorySegments().isArray()
                        && request.memorySegments().size() == 1)))
                .thenReturn(artifactId);
        when(repository.findArtifact(ACCOUNT_ID, buildId))
                .thenReturn(Optional.of(Map.of(
                        "artifactId", artifactId,
                        "messages", List.of(),
                        "contentHash", "sha256:artifact",
                        "tokenCount", 100,
                        "tokenizerVersion", "tokenizer-v1",
                        "memorySegments", List.of(Map.of(
                                "segmentId", "seg-1", "status", "FROZEN", "cacheHit", true)))));

        mvc.perform(post("/internal/v1/context/builds/{buildId}/artifact", buildId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"accountId":"10000000-0000-0000-0000-000000000001",
                                 "messages":[{"order":0,"role":"system","content":"规则"}],
                                 "contentHash":"sha256:artifact","tokenCount":100,
                                 "tokenizerVersion":"tokenizer-v1",
                                 "memorySegments":[{"segmentId":"seg-1","status":"FROZEN","cacheHit":true}]}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.artifactId").value(artifactId.toString()));

        mvc.perform(get("/internal/v1/context/builds/{buildId}/artifact", buildId)
                        .param("accountId", ACCOUNT_ID.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.memorySegments[0].segmentId").value("seg-1"))
                .andExpect(jsonPath("$.memorySegments[0].cacheHit").value(true));
    }
}
