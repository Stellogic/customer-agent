package com.stellogic.customeragent.closure;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import org.junit.jupiter.api.Test;

class ClosureDeadlineTest {
    private static final Instant RESOLVED_AT = Instant.parse("2026-08-09T00:00:00Z");

    @Test
    void sameIssueReplyOneInstantBeforeDeadlineCanReopen() {
        assertThat(ClosureDeadline.isOpen(RESOLVED_AT, Instant.parse("2026-08-11T23:59:59.999999999Z")))
                .isTrue();
    }

    @Test
    void deadlineIsClosedAtExactlySeventyTwoHoursAndAfterwards() {
        assertThat(ClosureDeadline.isOpen(RESOLVED_AT, Instant.parse("2026-08-12T00:00:00Z")))
                .isFalse();
        assertThat(ClosureDeadline.isOpen(RESOLVED_AT, Instant.parse("2026-08-12T00:00:00.000000001Z")))
                .isFalse();
    }
}
