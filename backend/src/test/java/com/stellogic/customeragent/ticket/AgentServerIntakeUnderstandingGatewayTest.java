package com.stellogic.customeragent.ticket;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.Test;

class AgentServerIntakeUnderstandingGatewayTest {
    private static final ProposedIntakeIssue PACKAGE_NOT_RECEIVED =
            new ProposedIntakeIssue("PACKAGE_NOT_RECEIVED", "包裹未收到");
    private static final ProposedIntakeIssue DUPLICATE_CHARGE =
            new ProposedIntakeIssue("DUPLICATE_CHARGE", "重复扣款");

    @Test
    void acceptsOnlyThePendingHeadBeingConfirmedWhileKeepingTheTail() {
        assertThat(
                        consistent(
                                "NEEDS_CLARIFICATION",
                                List.of(PACKAGE_NOT_RECEIVED, DUPLICATE_CHARGE),
                                List.of("LOGISTICS_DELAY"),
                                List.of(PACKAGE_NOT_RECEIVED),
                                List.of("DUPLICATE_CHARGE", "LOGISTICS_DELAY")))
                .isTrue();
    }

    @Test
    void rejectsDroppingAnExistingIssue() {
        assertThat(
                        consistent(
                                "NEEDS_CLARIFICATION",
                                List.of(),
                                List.of("DUPLICATE_CHARGE"),
                                List.of(PACKAGE_NOT_RECEIVED),
                                List.of("DUPLICATE_CHARGE")))
                .isFalse();
    }

    @Test
    void rejectsPromotingMoreThanThePendingHeadInOneTurn() {
        assertThat(
                        consistent(
                                "READY_TO_CONFIRM",
                                List.of(PACKAGE_NOT_RECEIVED, DUPLICATE_CHARGE),
                                List.of(),
                                List.of(),
                                List.of("PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE")))
                .isFalse();
    }

    @Test
    void rejectsDroppingThePendingTail() {
        assertThat(
                        consistent(
                                "NEEDS_CLARIFICATION",
                                List.of(PACKAGE_NOT_RECEIVED),
                                List.of(),
                                List.of(),
                                List.of("PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE")))
                .isFalse();
    }

    private static boolean consistent(
            String status,
            List<ProposedIntakeIssue> issues,
            List<String> pending,
            List<ProposedIntakeIssue> currentIssues,
            List<String> currentPending) {
        return AgentServerIntakeUnderstandingGateway.hasConsistentShape(
                "UNDERSTANDING",
                status,
                "ORDER-DELAY-001",
                issues,
                pending,
                "ORDER-DELAY-001",
                currentIssues,
                currentPending);
    }
}
