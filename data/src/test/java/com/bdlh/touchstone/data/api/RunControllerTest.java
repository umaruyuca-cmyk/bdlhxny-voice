package com.bdlh.touchstone.data.api;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.bdlh.touchstone.data.repository.RunRepository;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class RunControllerTest {
    private RunRepository repository;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        repository = Mockito.mock(RunRepository.class);
        mvc = MockMvcBuilders.standaloneSetup(new RunController(repository)).build();
    }

    @Test
    void savesModelCallsWithMessageSnapshots() throws Exception {
        String runId = UUID.randomUUID().toString();
        mvc.perform(post("/internal/v1/runs/{id}/model-calls", runId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"calls":[{
                                  "sequence": 0,
                                  "purpose": "AGENT",
                                  "model": "glm-4.7-flash",
                                  "requestHash": "sha256:req",
                                  "responseHash": "sha256:res",
                                  "inputTokens": 120,
                                  "outputTokens": 30,
                                  "durationMs": 820,
                                  "retryCount": 0,
                                  "status": "COMPLETE",
                                  "messages": [{
                                    "messageOrder": 0,
                                    "role": "system",
                                    "content": "系统提示",
                                    "tokens": 3,
                                    "contentHash": "sha256:m0"
                                  }]
                                }]}
                                """))
                .andExpect(status().isAccepted());

        ArgumentCaptor<com.bdlh.touchstone.data.domain.RunPayloads.SaveModelCallsRequest> captor =
                ArgumentCaptor.forClass(
                        com.bdlh.touchstone.data.domain.RunPayloads.SaveModelCallsRequest.class);
        verify(repository).saveModelCalls(Mockito.eq(UUID.fromString(runId)), captor.capture());
        var call = captor.getValue().calls().get(0);
        org.junit.jupiter.api.Assertions.assertEquals(120, call.inputTokens());
        org.junit.jupiter.api.Assertions.assertEquals("system", call.messages().get(0).role());
    }

    @Test
    void savesToolCallsAndGuardrailChecks() throws Exception {
        String runId = UUID.randomUUID().toString();
        mvc.perform(post("/internal/v1/runs/{id}/tool-calls", runId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"calls":[{
                                  "sequence": 1,
                                  "toolName": "market.get_realtime_quote",
                                  "arguments": {"symbol": "300750"},
                                  "argumentsHash": "sha256:args",
                                  "status": "SUCCESS",
                                  "resultSummary": {"price": 185.5},
                                  "resultHash": "sha256:res",
                                  "durationMs": 12,
                                  "fixtureHit": true
                                }]}
                                """))
                .andExpect(status().isAccepted());

        mvc.perform(post("/internal/v1/runs/{id}/guardrail-checks", runId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"checks":[{
                                  "sequence": 0,
                                  "stage": "action",
                                  "decision": "block",
                                  "auditCode": "G3-AUTH-001",
                                  "reasons": ["该工具仅机主可调用"],
                                  "toolName": "portfolio.get_current_positions",
                                  "durationMs": 1
                                }]}
                                """))
                .andExpect(status().isAccepted());

        verify(repository).saveToolCalls(Mockito.eq(UUID.fromString(runId)), Mockito.any());
        verify(repository).saveGuardrailChecks(Mockito.eq(UUID.fromString(runId)), Mockito.any());
    }

    @Test
    void savesMeasurementsWithNonNegativeFields() throws Exception {
        String runId = UUID.randomUUID().toString();
        mvc.perform(post("/internal/v1/runs/{id}/measurements", runId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"queueMs":0,"snapshotMs":0,"contextCollectMs":0,"contextCompressMs":0,
                                 "toolLoadingMs":0,"llmMs":820,"toolMs":31,"guardrailMs":2,"judgmentMs":5,
                                 "firstOutputMs":1650,"totalDurationMs":11120,
                                 "promptTokens":12840,"cachedPromptTokens":0,"completionTokens":420,
                                 "compressionInputTokens":0,"compressionOutputTokens":0}
                                """))
                .andExpect(status().isAccepted());

        verify(repository).saveMeasurements(Mockito.eq(UUID.fromString(runId)), Mockito.any());
    }

    @Test
    void savesArtifactRegistration() throws Exception {
        String runId = UUID.randomUUID().toString();
        mvc.perform(post("/internal/v1/runs/{id}/artifacts", runId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"artifactType":"run_full",
                                 "storageRef":"runs/%s.json",
                                 "contentHash":"sha256:artifact",
                                 "publicArtifact":false}
                                """.formatted(runId)))
                .andExpect(status().isAccepted());

        verify(repository).saveArtifact(Mockito.eq(UUID.fromString(runId)), Mockito.any());
    }

    @Test
    void listsBatchesWithDefaultLimitAndClampsRange() throws Exception {
        UUID cursor = UUID.randomUUID();
        java.util.Map<String, Object> emptyPage = new java.util.LinkedHashMap<>();
        emptyPage.put("batches", java.util.List.of());
        emptyPage.put("nextCursor", null);
        when(repository.listBatches(20, null)).thenReturn(emptyPage);
        when(repository.listBatches(100, cursor)).thenReturn(emptyPage);

        mvc.perform(get("/internal/v1/batches"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.batches").isArray());

        mvc.perform(get("/internal/v1/batches")
                        .param("limit", "500")
                        .param("cursor", cursor.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.batches").isArray());
        verify(repository).listBatches(100, cursor);
    }

    @Test
    void returnsRunDetailFromRepository() throws Exception {
        UUID runId = UUID.randomUUID();
        when(repository.getRunDetail(runId)).thenReturn(Map.of(
                "id", runId,
                "events", java.util.List.of(),
                "modelCalls", java.util.List.of(),
                "toolCalls", java.util.List.of(),
                "guardrailChecks", java.util.List.of(),
                "measurements", java.util.List.of(),
                "artifacts", java.util.List.of()));

        mvc.perform(get("/internal/v1/runs/{id}/detail", runId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(runId.toString()))
                .andExpect(jsonPath("$.events").isArray())
                .andExpect(jsonPath("$.toolCalls").isArray());
    }

    @Test
    void returnsNotFoundForUnknownRunDetail() throws Exception {
        UUID runId = UUID.randomUUID();
        when(repository.getRunDetail(runId))
                .thenThrow(new org.springframework.dao.EmptyResultDataAccessException(1));

        mvc.perform(get("/internal/v1/runs/{id}/detail", runId))
                .andExpect(status().isNotFound());
    }

    @Test
    void rejectsBlankArtifactPayload() throws Exception {
        String runId = UUID.randomUUID().toString();
        mvc.perform(post("/internal/v1/runs/{id}/artifacts", runId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"artifactType\":\"\",\"storageRef\":\"\",\"contentHash\":\"\"}"))
                .andExpect(status().isBadRequest());
    }
}
