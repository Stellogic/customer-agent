package com.stellogic.customeragent.sla;

import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/support")
public final class SupportSlaController {
    private static final String SUPPORT_ID = "support-demo";
    private final SupportSlaProjectionService service;

    SupportSlaController(SupportSlaProjectionService service) {
        this.service = service;
    }

    @GetMapping("/sla/notifications")
    List<SlaWarningNotification> notifications(
            @RequestHeader(value = "X-Synthetic-Support-Id", required = false) String supportId) {
        return service.notifications(requireSupport(supportId));
    }

    @GetMapping("/escalations")
    List<SharedEscalationSummary> escalations(
            @RequestHeader(value = "X-Synthetic-Support-Id", required = false) String supportId) {
        requireSupport(supportId);
        return service.escalations();
    }

    private static String requireSupport(String supportId) {
        if (!SUPPORT_ID.equals(supportId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "support identity required");
        }
        return supportId;
    }
}
