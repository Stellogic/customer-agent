package com.stellogic.customeragent.queue;

import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/support/queue")
public final class SharedSupportQueueController {
    private final SharedSupportQueueProjectionService service;

    SharedSupportQueueController(SharedSupportQueueProjectionService service) {
        this.service = service;
    }

    @GetMapping
    List<SharedQueueSummary> queue() {
        return service.queue();
    }
}
