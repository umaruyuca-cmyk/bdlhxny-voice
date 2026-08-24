package com.bdlh.runtime.api;

import com.bdlh.runtime.messaging.OutboxDtos.CompletionResult;
import com.bdlh.runtime.messaging.FinancialTaskStoreService;
import com.bdlh.runtime.messaging.TaskOutboxService;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class TaskOutboxControllerTest {

    private final JavaDataAccessGuard guard = mock(JavaDataAccessGuard.class);
    private final TaskOutboxService service = mock(TaskOutboxService.class);
    private final FinancialTaskStoreService taskStore = mock(FinancialTaskStoreService.class);
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        mvc = MockMvcBuilders.standaloneSetup(new TaskOutboxController(guard, service, taskStore)).build();
        when(guard.resolveUserId(7L)).thenReturn(7L);
    }

    @Test
    void completionUsesGuardResolvedOwner() throws Exception {
        UUID eventId = UUID.randomUUID();
        when(service.completeTaskAndEnqueueNotification(eq("7"), eq("task-1"), any()))
                .thenReturn(new CompletionResult(eventId, "PENDING", false));

        mvc.perform(post("/internal/v1/tasks/task-1/complete-notification")
                        .param("user_id", "7")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"expectedVersion\":2,\"eventId\":\"" + eventId
                                + "\",\"idempotencyKey\":\"task-notification:wakeup-1\","
                                + "\"notificationPayload\":{\"title\":\"ready\"}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.eventId").value(eventId.toString()))
                .andExpect(jsonPath("$.status").value("PENDING"));

        verify(guard).resolveUserId(7L);
        verify(service).completeTaskAndEnqueueNotification(eq("7"), eq("task-1"), any());
    }
}
