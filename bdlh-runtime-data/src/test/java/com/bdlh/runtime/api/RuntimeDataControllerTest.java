package com.bdlh.runtime.api;

import com.bdlh.runtime.runtime.RuntimeDataDtos.AnalysisHistoryResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.ChatSessionResponse;
import com.bdlh.runtime.runtime.RuntimeDataDtos.RunLocationResponse;
import com.bdlh.runtime.runtime.RuntimeDataService;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class RuntimeDataControllerTest {

    private final JavaDataAccessGuard guard = mock(JavaDataAccessGuard.class);
    private final RuntimeDataService service = mock(RuntimeDataService.class);
    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.standaloneSetup(new RuntimeDataController(guard, service)).build();
        when(guard.resolveUserId(7L)).thenReturn(7L);
    }

    @Test
    void sessionWriteUsesGuardResolvedUserInsteadOfRequestBodyIdentity() throws Exception {
        when(service.ensureSession(eq(7L), eq("requested-session"))).thenReturn(session());

        mvc.perform(post("/internal/v1/runtime/sessions")
                        .param("user_id", "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"requestedSessionId\":\"requested-session\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sessionId").value("session-1"))
                .andExpect(jsonPath("$.title").value("新的对话"));

        verify(guard).resolveUserId(7L);
        verify(service).ensureSession(7L, "requested-session");
    }

    @Test
    void runAndHistoryWritesUseUseCasePayloads() throws Exception {
        OffsetDateTime now = OffsetDateTime.parse("2026-08-15T00:00:00Z");
        when(service.upsertRun(eq(7L), eq("run-1"), any())).thenReturn(
                new RunLocationResponse("run-1", "thread-1", "cp-1", "legacy_root_graph", now));
        when(service.saveHistory(eq(7L), eq("history-1"), any())).thenReturn(
                new AnalysisHistoryResponse(
                        "history-1", "thread-1", "run-1", "SUCCESS",
                        objectMapper.readTree("{\"intent\":\"analysis\"}"), now));

        mvc.perform(put("/internal/v1/runtime/runs/run-1")
                        .param("user_id", "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"threadId\":\"thread-1\",\"checkpointId\":\"cp-1\",\"runtimePath\":\"legacy_root_graph\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runId").value("run-1"));

        mvc.perform(put("/internal/v1/runtime/history/history-1")
                        .param("user_id", "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"status\":\"SUCCESS\",\"payload\":{\"intent\":\"analysis\"}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.historyId").value("history-1"))
                .andExpect(jsonPath("$.payload.intent").value("analysis"));

        verify(service).upsertRun(eq(7L), eq("run-1"), any());
        verify(service).saveHistory(eq(7L), eq("history-1"), any());
    }

    private static ChatSessionResponse session() {
        return new ChatSessionResponse(
                "session-1", "新的对话", List.of(), null, null, null, null,
                null, false, null,
                OffsetDateTime.parse("2026-08-15T00:00:00Z"));
    }
}
