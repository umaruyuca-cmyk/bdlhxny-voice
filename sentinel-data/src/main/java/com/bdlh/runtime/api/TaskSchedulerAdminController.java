package com.bdlh.runtime.api;

import com.bdlh.runtime.messaging.FinancialTaskStoreService;
import com.bdlh.runtime.messaging.OutboxDtos.TaskSnapshot;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** Service-token-only scheduler operations, hosted in the same Data Plane JVM. */
@RestController
@RequestMapping("/internal/v1/task-scheduler")
public class TaskSchedulerAdminController {

    private final JavaDataAccessGuard accessGuard;
    private final FinancialTaskStoreService taskStoreService;

    public TaskSchedulerAdminController(JavaDataAccessGuard accessGuard, FinancialTaskStoreService taskStoreService) {
        this.accessGuard = accessGuard;
        this.taskStoreService = taskStoreService;
    }

    @PostMapping("/claim-due")
    public List<TaskSnapshot> claimDue(@RequestParam(defaultValue = "50") int limit) {
        accessGuard.requireInternalService();
        return taskStoreService.claimDue(limit, null);
    }

    @PostMapping("/expire-due")
    public int expireDue() {
        accessGuard.requireInternalService();
        return taskStoreService.expireDue(null);
    }

    @PostMapping("/recover-stale")
    public int recoverStale() {
        accessGuard.requireInternalService();
        return taskStoreService.recoverStale(null, null);
    }
}
