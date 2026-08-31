package com.bdlh.touchstone.data.api;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.bdlh.touchstone.data.repository.ContextOpsRepository;
import com.bdlh.touchstone.data.repository.ContextOpsRepository.GrantConflict;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class ContextOpsControllerTest {
    private static final UUID OWNER_ID = UUID.fromString("10000000-0000-0000-0000-000000000001");
    private static final UUID GRANTEE_ID = UUID.fromString("20000000-0000-0000-0000-000000000002");

    private ContextOpsRepository repository;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        repository = Mockito.mock(ContextOpsRepository.class);
        mvc = MockMvcBuilders.standaloneSetup(new ContextOpsController(repository)).build();
    }

    @Test
    void createsGrantAndMapsConflictTo409() throws Exception {
        when(repository.createGrant(Mockito.any())).thenReturn(Map.of(
                "grantId", UUID.randomUUID(),
                "scope", "ARTIFACT_READ"));

        mvc.perform(post("/internal/v1/context/ops/access-grants")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "ownerAccountId": "%s",
                                  "granteeAccountId": "%s",
                                  "scope": "ARTIFACT_READ",
                                  "buildId": "ctxb-1"
                                }
                                """.formatted(OWNER_ID, GRANTEE_ID)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.scope").value("ARTIFACT_READ"));

        when(repository.createGrant(Mockito.any())).thenThrow(new GrantConflict("同样的活跃授权已存在"));
        mvc.perform(post("/internal/v1/context/ops/access-grants")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "ownerAccountId": "%s",
                                  "granteeAccountId": "%s",
                                  "scope": "ARTIFACT_READ"
                                }
                                """.formatted(OWNER_ID, GRANTEE_ID)))
                .andExpect(status().isConflict());
    }

    @Test
    void listsGrantsForOwnerOnly() throws Exception {
        when(repository.listGrants(OWNER_ID)).thenReturn(List.of(Map.of(
                "grantId", UUID.randomUUID(),
                "granteeAccountId", GRANTEE_ID.toString(),
                "scope", "ARTIFACT_READ")));

        mvc.perform(get("/internal/v1/context/ops/access-grants")
                        .param("ownerAccountId", OWNER_ID.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.grants[0].granteeAccountId").value(GRANTEE_ID.toString()));
    }

    @Test
    void revokeReturns204Or404ByOwner() throws Exception {
        UUID grantId = UUID.randomUUID();
        when(repository.revokeGrant(OWNER_ID, grantId)).thenReturn(true, false);

        mvc.perform(delete("/internal/v1/context/ops/access-grants/{grantId}", grantId)
                        .param("ownerAccountId", OWNER_ID.toString()))
                .andExpect(status().isNoContent());
        mvc.perform(delete("/internal/v1/context/ops/access-grants/{grantId}", grantId)
                        .param("ownerAccountId", OWNER_ID.toString()))
                .andExpect(status().isNotFound());
    }

    @Test
    void activeGrantLookupAnswersGrantedFlag() throws Exception {
        when(repository.hasActiveGrant(OWNER_ID, GRANTEE_ID, "ctxb-1")).thenReturn(true);

        mvc.perform(get("/internal/v1/context/ops/access-grants/active")
                        .param("ownerAccountId", OWNER_ID.toString())
                        .param("granteeAccountId", GRANTEE_ID.toString())
                        .param("buildId", "ctxb-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.granted").value(true));
    }

    @Test
    void writesAuditWithoutBody() throws Exception {
        mvc.perform(post("/internal/v1/context/ops/audit")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "accountId": "%s",
                                  "action": "CONTEXT_ARTIFACT_DOWNLOAD",
                                  "succeeded": true,
                                  "detail": {"buildId": "ctxb-1", "via": "owner"}
                                }
                                """.formatted(OWNER_ID)))
                .andExpect(status().isNoContent());

        verify(repository).writeAudit(Mockito.argThat(request ->
                request != null
                        && "CONTEXT_ARTIFACT_DOWNLOAD".equals(request.action())
                        && request.succeeded()
                        && request.detail() != null));
    }

    @Test
    void listsOwnAuditWithAccountIdAndCrossOwnerWithout() throws Exception {
        when(repository.listAudit(OWNER_ID, 50)).thenReturn(List.of(Map.of(
                "action", "CONTEXT_ARTIFACT_DOWNLOAD", "succeeded", true)));
        when(repository.listAudit(null, 20)).thenReturn(List.of(Map.of(
                "action", "CONTEXT_BUILD_CREATED", "succeeded", true)));

        mvc.perform(get("/internal/v1/context/ops/audit")
                        .param("accountId", OWNER_ID.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.events[0].action").value("CONTEXT_ARTIFACT_DOWNLOAD"));

        mvc.perform(get("/internal/v1/context/ops/audit").param("limit", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.events[0].action").value("CONTEXT_BUILD_CREATED"));
        verify(repository).listAudit(isNull(), eq(20));
    }

    @Test
    void listsCrossOwnerBuildsWithPaginationFields() throws Exception {
        java.util.Map<String, Object> payload = new java.util.LinkedHashMap<>();
        payload.put("builds", List.of(Map.of(
                "buildId", "b-1",
                "status", "COMPLETED",
                "llmUsage", "{\"summary_calls\": 1}")));
        payload.put("total", 1);
        payload.put("nextCursor", null);
        when(repository.listBuildsCrossOwner(50, 0)).thenReturn(payload);

        mvc.perform(get("/internal/v1/context/ops/builds"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.builds[0].buildId").value("b-1"))
                .andExpect(jsonPath("$.builds[0].llmUsage").isNotEmpty())
                .andExpect(jsonPath("$.total").value(1));
    }

    @Test
    void listsRecentSegmentsForAnalysisSampling() throws Exception {
        when(repository.listRecentSegmentsCrossOwner(5)).thenReturn(List.of(Map.of(
                "segmentId", "11111111-1111-1111-1111-111111111111",
                "summaryContent", "摘要正文",
                "sourceContents", "[\"原文一\"]")));

        mvc.perform(get("/internal/v1/context/ops/segments/recent").param("limit", "5"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.segments[0].segmentId").value("11111111-1111-1111-1111-111111111111"))
                .andExpect(jsonPath("$.segments[0].summaryContent").value("摘要正文"));
    }

    @Test
    void savesAndListsQualityChecks() throws Exception {
        when(repository.saveQualityCheck(Mockito.any())).thenReturn(Map.of(
                "checkId", UUID.randomUUID(), "verdict", "PASS"));
        when(repository.listQualityChecks(OWNER_ID, "session-1", 50)).thenReturn(List.of(Map.of(
                "verdict", "WARN", "missingFacts", "[\"关键事实缺失\"]")));

        mvc.perform(post("/internal/v1/context/ops/segment-quality-checks")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "accountId": "%s",
                                  "segmentId": "11111111-1111-1111-1111-111111111111",
                                  "sessionId": "session-1",
                                  "verdict": "PASS",
                                  "missingFacts": [],
                                  "hallucinations": [],
                                  "promptVersion": "segment-judge-v1",
                                  "sourceHashAtCheck": "sha256:x"
                                }
                                """.formatted(OWNER_ID)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.verdict").value("PASS"));

        mvc.perform(get("/internal/v1/context/ops/segment-quality-checks")
                        .param("accountId", OWNER_ID.toString())
                        .param("sessionId", "session-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.checks[0].verdict").value("WARN"));
    }

    @Test
    void analysisRunLifecycleStartsAndFinishes() throws Exception {
        UUID runId = UUID.randomUUID();
        when(repository.startAnalysisRun("SCHEDULED")).thenReturn(runId);
        when(repository.finishAnalysisRun(Mockito.eq(runId), Mockito.any())).thenReturn(true, false);

        mvc.perform(post("/internal/v1/context/ops/analysis-runs")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"triggerSource": "SCHEDULED"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("RUNNING"));

        mvc.perform(put("/internal/v1/context/ops/analysis-runs/{runId}", runId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "status": "COMPLETED",
                                  "sampledSegments": 5,
                                  "judgeCalls": 5,
                                  "judgeErrors": 0,
                                  "report": {"threshold_groups": []}
                                }
                                """))
                .andExpect(status().isNoContent());
        mvc.perform(put("/internal/v1/context/ops/analysis-runs/{runId}", runId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"status": "FAILED", "errorCode": "LLM_UNAVAILABLE"}
                                """))
                .andExpect(status().isNotFound());
    }

    @Test
    void listsAnalysisRunsWithReport() throws Exception {
        when(repository.listAnalysisRuns(5)).thenReturn(List.of(Map.of(
                "runId", UUID.randomUUID(),
                "status", "COMPLETED",
                "triggerSource", "SCHEDULED",
                "report", "{\"threshold_groups\": []}")));

        mvc.perform(get("/internal/v1/context/ops/analysis-runs").param("limit", "5"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runs[0].status").value("COMPLETED"))
                .andExpect(jsonPath("$.runs[0].report").isNotEmpty());
    }
}
