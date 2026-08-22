package com.stellogic.customeragent.sla;

import java.util.List;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/support")
public final class SupportSlaController {
    private final SupportSlaProjectionService service;

    SupportSlaController(SupportSlaProjectionService service) {
        this.service = service;
    }

    @GetMapping("/sla/notifications")
    List<SlaWarningNotification> notifications(Authentication authentication) {
        return service.notifications(authentication.getName());
    }

    @GetMapping("/escalations")
    List<SharedEscalationSummary> escalations(Authentication authentication) {
        return service.escalations();
    }
}
