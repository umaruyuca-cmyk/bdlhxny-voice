package com.bdlh.runtime.api;

import com.bdlh.runtime.messaging.NotificationProjectionService;
import com.bdlh.runtime.messaging.NotificationProjectionService.NotificationView;
import com.bdlh.runtime.security.JavaDataAccessGuard;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/internal/v1/notifications")
public class NotificationController {

    private final JavaDataAccessGuard accessGuard;
    private final NotificationProjectionService notificationProjectionService;

    public NotificationController(
            JavaDataAccessGuard accessGuard,
            NotificationProjectionService notificationProjectionService) {
        this.accessGuard = accessGuard;
        this.notificationProjectionService = notificationProjectionService;
    }

    @GetMapping
    public List<NotificationView> list(
            @RequestParam(name = "user_id", required = false) Long requestedUserId,
            @RequestParam(defaultValue = "50") int limit) {
        return notificationProjectionService.listForUser(
                String.valueOf(accessGuard.resolveUserId(requestedUserId)), limit);
    }
}
