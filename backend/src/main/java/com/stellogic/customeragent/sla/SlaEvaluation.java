package com.stellogic.customeragent.sla;

import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.Set;

final class SlaEvaluation {
    static final long FIRST_RESPONSE_TARGET_SECONDS = Duration.ofMinutes(15).toSeconds();
    static final long RESOLUTION_TARGET_SECONDS = Duration.ofHours(24).toSeconds();

    private SlaEvaluation() {}

    static Set<SlaFact> dueFacts(TicketSlaSnapshot ticket, Instant now) {
        Set<SlaFact> due = new LinkedHashSet<>();
        long firstResponseElapsed = elapsed(ticket.createdAt(),
                ticket.firstRespondedAt() == null ? now : ticket.firstRespondedAt());
        addThresholdFacts(due, SlaObjective.FIRST_RESPONSE, firstResponseElapsed, FIRST_RESPONSE_TARGET_SECONDS);

        long resolutionElapsed = ticket.resolutionElapsedSeconds();
        if (ticket.resolutionRunningSince() != null
                && !"RESOLVED".equals(ticket.lifecycleState())
                && !"CLOSED".equals(ticket.lifecycleState())) {
            resolutionElapsed += elapsed(ticket.resolutionRunningSince(), now);
        }
        addThresholdFacts(due, SlaObjective.RESOLUTION, resolutionElapsed, RESOLUTION_TARGET_SECONDS);
        return Set.copyOf(due);
    }

    private static void addThresholdFacts(Set<SlaFact> due, SlaObjective objective, long elapsed, long target) {
        long warning = target * 80 / 100;
        if (elapsed >= warning) due.add(new SlaFact(objective, SlaFactType.WARNING, elapsed));
        if (elapsed >= target) due.add(new SlaFact(objective, SlaFactType.BREACH, elapsed));
    }

    private static long elapsed(Instant start, Instant end) {
        return Math.max(0, Duration.between(start, end).toSeconds());
    }
}

enum SlaObjective {
    FIRST_RESPONSE,
    RESOLUTION
}

enum SlaFactType {
    WARNING,
    BREACH
}

record SlaFact(SlaObjective objective, SlaFactType type, long elapsedSeconds) {}

record TicketSlaSnapshot(
        Instant createdAt,
        Instant firstRespondedAt,
        long resolutionElapsedSeconds,
        Instant resolutionRunningSince,
        String lifecycleState) {}
