package com.stellogic.customeragent.ticket;

final class RequestIdentityConflictException extends RuntimeException {}

final class TicketNotFoundException extends RuntimeException {}

final class InvalidCustomerRequestException extends RuntimeException {
    InvalidCustomerRequestException(String message) {
        super(message);
    }
}

final class CustomerAuthenticationException extends RuntimeException {}

final class ProjectionCursorException extends RuntimeException {}
