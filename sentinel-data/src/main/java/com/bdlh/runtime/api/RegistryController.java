package com.bdlh.runtime.api;

import com.bdlh.runtime.registry.RegistrySnapshotService;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Internal, read-only Registry snapshot API. */
@RestController
@RequestMapping("/internal/v1/registry")
public class RegistryController {

    private final JavaDataAccessGuard accessGuard;
    private final RegistrySnapshotService registrySnapshotService;

    public RegistryController(
            JavaDataAccessGuard accessGuard,
            RegistrySnapshotService registrySnapshotService) {
        this.accessGuard = accessGuard;
        this.registrySnapshotService = registrySnapshotService;
    }

    @GetMapping("/snapshot")
    public JsonNode snapshot() {
        accessGuard.requireInternalService();
        return registrySnapshotService.snapshot();
    }
}
