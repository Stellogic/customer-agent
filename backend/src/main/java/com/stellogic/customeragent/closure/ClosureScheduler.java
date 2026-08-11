package com.stellogic.customeragent.closure;

import java.time.Clock;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
final class ClosureScheduler {
    private final ClosureService service;
    private final Clock clock;

    ClosureScheduler(ClosureService service, Clock clock) {
        this.service = service;
        this.clock = clock;
    }

    @Scheduled(fixedDelayString = "${baseline.closure.poll-delay:1000}")
    void closeDueTickets() {
        var now = clock.instant();
        for (var ticketId : service.dueTicketIds(now)) service.closeIfDue(ticketId, now);
    }
}
