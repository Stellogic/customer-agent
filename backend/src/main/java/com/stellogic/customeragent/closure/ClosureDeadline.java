package com.stellogic.customeragent.closure;

import java.time.Duration;
import java.time.Instant;

final class ClosureDeadline {
    static final Duration WAITING_PERIOD = Duration.ofHours(72);

    private ClosureDeadline() {}

    static boolean isOpen(Instant resolvedAt, Instant replyAt) {
        return replyAt.isBefore(resolvedAt.plus(WAITING_PERIOD));
    }
}
