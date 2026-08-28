package com.stellogic.customeragent.ticket;

final class RequestIdentityConflictException extends RuntimeException {}

final class IntakeRequestIdentityConflictException extends RuntimeException {
    private final CustomerIntakeSnapshot authoritativeSnapshot;

    IntakeRequestIdentityConflictException(CustomerIntakeSnapshot authoritativeSnapshot) {
        this.authoritativeSnapshot = authoritativeSnapshot;
    }

    CustomerIntakeSnapshot authoritativeSnapshot() {
        return authoritativeSnapshot;
    }
}

final class TicketNotFoundException extends RuntimeException {}

final class InvalidCustomerRequestException extends RuntimeException {
    InvalidCustomerRequestException(String message) {
        super(message);
    }
}

final class CustomerAuthenticationException extends RuntimeException {}

final class ProjectionCursorException extends RuntimeException {}

final class IncompatibleCustomerSchemaException extends RuntimeException {}

final class CustomerMessageNotAcceptedException extends RuntimeException {}

final class IntakeNotFoundException extends RuntimeException {}

final class IntakeNotReadyException extends RuntimeException {}

final class IntakeCandidateStaleException extends RuntimeException {}

final class IntakeArchivedException extends RuntimeException {}

final class IntakeVersionConflictException extends RuntimeException {}

final class IntakeAgentUnavailableException extends RuntimeException {}
