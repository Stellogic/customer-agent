package com.stellogic.customeragent.sla;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Set;
import org.junit.jupiter.api.Test;

class SlaEvaluationTest {
    private static final Instant CREATED = Instant.parse("2026-08-09T00:00:00Z");

    @Test
    void firstResponseUsesContinuousTimeAndEmitsExactBoundaries() {
        assertThat(SlaEvaluation.dueFacts(snapshot(null, 0, CREATED), CREATED.plusSeconds(719)))
                .isEmpty();
        assertThat(SlaEvaluation.dueFacts(snapshot(CREATED.plusSeconds(720), 0, CREATED), CREATED.plusSeconds(900)))
                .containsExactly(new SlaFact(SlaObjective.FIRST_RESPONSE, SlaFactType.WARNING, 720));
        assertThat(SlaEvaluation.dueFacts(snapshot(CREATED.plusSeconds(900), 0, CREATED), CREATED.plusSeconds(901)))
                .containsExactlyInAnyOrder(
                        new SlaFact(SlaObjective.FIRST_RESPONSE, SlaFactType.WARNING, 900),
                        new SlaFact(SlaObjective.FIRST_RESPONSE, SlaFactType.BREACH, 900));
    }

    @Test
    void resolutionUsesAccumulatedTimeAndOnlyARunningClockAdvances() {
        long warning = 69_120;
        assertThat(SlaEvaluation.dueFacts(snapshot(CREATED, warning - 1, null), CREATED.plusSeconds(100_000)))
                .doesNotContain(new SlaFact(SlaObjective.RESOLUTION, SlaFactType.WARNING, warning - 1));
        assertThat(SlaEvaluation.dueFacts(snapshot(CREATED, warning, null), CREATED.plusSeconds(100_000)))
                .contains(new SlaFact(SlaObjective.RESOLUTION, SlaFactType.WARNING, warning));
        assertThat(SlaEvaluation.dueFacts(snapshot(CREATED, 86_399, CREATED), CREATED.plusSeconds(1)))
                .contains(new SlaFact(SlaObjective.RESOLUTION, SlaFactType.BREACH, 86_400));
    }

    @Test
    void resolvedTicketStopsAdvancingButStillMaterializesFactsFromItsFinalElapsedTime() {
        TicketSlaSnapshot resolved = new TicketSlaSnapshot(
                CREATED, CREATED.plusSeconds(900), 90_000, null, "RESOLVED");

        assertThat(SlaEvaluation.dueFacts(resolved, CREATED.plusSeconds(200_000)))
                .containsExactlyInAnyOrder(
                        new SlaFact(SlaObjective.FIRST_RESPONSE, SlaFactType.WARNING, 900),
                        new SlaFact(SlaObjective.FIRST_RESPONSE, SlaFactType.BREACH, 900),
                        new SlaFact(SlaObjective.RESOLUTION, SlaFactType.WARNING, 90_000),
                        new SlaFact(SlaObjective.RESOLUTION, SlaFactType.BREACH, 90_000));
    }

    @Test
    void reopenedTicketContinuesTheOriginalAccumulatedResolutionBudget() {
        TicketSlaSnapshot reopened = new TicketSlaSnapshot(
                CREATED, CREATED, 69_119, CREATED.plusSeconds(100_000), "INVESTIGATING");

        assertThat(SlaEvaluation.dueFacts(reopened, CREATED.plusSeconds(100_001)))
                .contains(new SlaFact(SlaObjective.RESOLUTION, SlaFactType.WARNING, 69_120));
    }

    private static TicketSlaSnapshot snapshot(
            Instant firstRespondedAt, long resolutionElapsedSeconds, Instant resolutionRunningSince) {
        return new TicketSlaSnapshot(
                CREATED, firstRespondedAt, resolutionElapsedSeconds, resolutionRunningSince, "INVESTIGATING");
    }
}
