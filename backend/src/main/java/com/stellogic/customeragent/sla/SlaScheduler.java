package com.stellogic.customeragent.sla;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
class SlaScheduler {
    private final SlaService service;

    SlaScheduler(SlaService service) {
        this.service = service;
    }

    @Scheduled(fixedDelayString = "${baseline.sla.poll-delay:1000}")
    void evaluateCurrentTickets() {
        var evaluatedAt = service.now();
        for (var ticketId : service.ticketIds()) service.evaluateTicket(ticketId, evaluatedAt);
    }
}
