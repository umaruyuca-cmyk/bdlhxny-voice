package com.bdlh.runtime.api;

import com.bdlh.runtime.messaging.MemoryCandidateService;
import com.bdlh.runtime.messaging.MemoryCandidateService.MemoryCandidateRequest;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/internal/v1/memory-candidates")
public class MemoryCandidateController {
    private final JavaDataAccessGuard accessGuard;
    private final MemoryCandidateService memoryCandidateService;

    public MemoryCandidateController(JavaDataAccessGuard accessGuard, MemoryCandidateService memoryCandidateService) {
        this.accessGuard = accessGuard;
        this.memoryCandidateService = memoryCandidateService;
    }

    @PostMapping
    public Map<String, UUID> enqueue(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @RequestBody MemoryCandidateRequest request) {
        UUID eventId = memoryCandidateService.enqueue(
                String.valueOf(accessGuard.resolveUserId(requestedUserId)), request);
        return Map.of("eventId", eventId);
    }
}
