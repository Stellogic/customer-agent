package com.stellogic.customeragent.queue;

import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/support/queue")
public final class SharedSupportQueueController {
    private static final String SUPPORT_ID = "support-demo";
    private final SharedSupportQueueProjectionService service;

    SharedSupportQueueController(SharedSupportQueueProjectionService service) {
        this.service = service;
    }

    @GetMapping
    List<SharedQueueSummary> queue(
            @RequestHeader(value = "X-Synthetic-Support-Id", required = false) String supportId) {
        if (!SUPPORT_ID.equals(supportId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "support identity required");
        }
        return service.queue();
    }
}
