package com.bdlh.runtime.api;

import com.bdlh.runtime.messaging.OutboxOperationsService;
import com.bdlh.runtime.messaging.OutboxOperationsService.OutboxStatus;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.UUID;

/** Internal operational endpoint.  It requires the service token, not a user JWT. */
@RestController
@RequestMapping("/internal/v1/ops/outbox")
public class OutboxOperationsController {

    private final JavaDataAccessGuard accessGuard;
    private final OutboxOperationsService outboxOperationsService;

    public OutboxOperationsController(
            JavaDataAccessGuard accessGuard,
            OutboxOperationsService outboxOperationsService) {
        this.accessGuard = accessGuard;
        this.outboxOperationsService = outboxOperationsService;
    }

    @GetMapping
    public OutboxStatus status() {
        accessGuard.requireInternalService();
        return outboxOperationsService.status();
    }

    @PostMapping("/{eventId}/requeue")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void requeue(@PathVariable UUID eventId) {
        accessGuard.requireInternalService();
        if (!outboxOperationsService.requeueFailed(eventId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "failed outbox event not found");
        }
    }
}
