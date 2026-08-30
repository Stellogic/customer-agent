package com.stellogic.customeragent.queue;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

record SupportCompensationPlan(
        String planCode,
        String compensationMethod,
        BigDecimal amount,
        BigDecimal capAmount,
        String currency,
        List<String> reasonCodes) {}

record SupportCompensationOptions(
        String schema, String policyVersion, List<SupportCompensationPlan> plans) {}

record SupportCompensationProposalResult(
        String schema,
        UUID ticketId,
        String requestId,
        UUID proposalRevisionId,
        int proposalRevision,
        String compensationMethod,
        BigDecimal amount,
        String currency,
        String status,
        String outcome,
        boolean replayed) {}

record SupportExceptionalCompensationResult(
        String schema,
        UUID ticketId,
        String requestId,
        UUID exceptionalRequestId,
        String reasonCode,
        String status,
        String outcome,
        boolean replayed) {}

final class SupportCompensationNotAllowedException extends RuntimeException {
    private final String code;

    SupportCompensationNotAllowedException(String code) {
        this.code = code;
    }

    String code() {
        return code;
    }
}

final class SupportCompensationConflictException extends RuntimeException {
    private final String code;

    SupportCompensationConflictException(String code) {
        this.code = code;
    }

    String code() {
        return code;
    }
}

final class SupportCompensationInvalidRequestException extends RuntimeException {
    private final String code;

    SupportCompensationInvalidRequestException(String code) {
        this.code = code;
    }

    String code() {
        return code;
    }
}

final class SupportCompensationIdentityConflictException extends RuntimeException {}
