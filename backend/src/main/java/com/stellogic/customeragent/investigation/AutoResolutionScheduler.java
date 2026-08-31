package com.stellogic.customeragent.investigation;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
final class AutoResolutionScheduler {
    private final AutoResolutionService service;

    AutoResolutionScheduler(AutoResolutionService service) {
        this.service = service;
    }

    @Scheduled(fixedDelayString = "${baseline.auto-resolution.poll-delay:1000}")
    void resolveDueTickets() {
        for (var ticketId : service.dueTicketIds()) service.resolveIfDue(ticketId);
    }
}
