package com.bdlh.runtime.api;

import com.bdlh.runtime.messaging.OutboxDtos.CompleteTaskNotificationRequest;
import com.bdlh.runtime.messaging.OutboxDtos.CompletionResult;
import com.bdlh.runtime.messaging.OutboxDtos.SaveTaskRequest;
import com.bdlh.runtime.messaging.OutboxDtos.TaskSnapshot;
import com.bdlh.runtime.messaging.FinancialTaskStoreService;
import com.bdlh.runtime.messaging.TaskOutboxService;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** Internal use case endpoint; it is not a generic SQL or event publishing API. */
@Tag(name = "Task Outbox API", description = "Transactional task completion and notification enqueueing")
@RestController
@RequestMapping("/internal/v1/tasks")
public class TaskOutboxController {

    private final JavaDataAccessGuard accessGuard;
    private final TaskOutboxService taskOutboxService;
    private final FinancialTaskStoreService taskStoreService;

    public TaskOutboxController(
            JavaDataAccessGuard accessGuard,
            TaskOutboxService taskOutboxService,
            FinancialTaskStoreService taskStoreService) {
        this.accessGuard = accessGuard;
        this.taskOutboxService = taskOutboxService;
        this.taskStoreService = taskStoreService;
    }

    @PostMapping
    public TaskSnapshot create(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @RequestBody SaveTaskRequest request) {
        return taskStoreService.create(owner(requestedUserId), request);
    }

    @org.springframework.web.bind.annotation.PutMapping("/{taskId}")
    public TaskSnapshot update(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String taskId,
            @RequestBody SaveTaskRequest request) {
        if (request == null || !taskId.equals(request.taskId())) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.BAD_REQUEST, "task_id must match path");
        }
        return taskStoreService.update(owner(requestedUserId), request);
    }

    @org.springframework.web.bind.annotation.GetMapping
    public List<TaskSnapshot> list(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @RequestParam(defaultValue = "50") int limit) {
        return taskStoreService.list(owner(requestedUserId), limit);
    }

    @org.springframework.web.bind.annotation.GetMapping("/{taskId}")
    public TaskSnapshot get(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String taskId) {
        return taskStoreService.get(owner(requestedUserId), taskId);
    }

    @PostMapping("/{taskId}/complete-notification")
    public CompletionResult completeTaskAndEnqueueNotification(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @PathVariable String taskId,
            @RequestBody CompleteTaskNotificationRequest request) {
        return taskOutboxService.completeTaskAndEnqueueNotification(owner(requestedUserId), taskId, request);
    }

    private String owner(Long requestedUserId) {
        return String.valueOf(accessGuard.resolveUserId(requestedUserId));
    }
}
