package com.stellogic.customeragent.closure;

final class ClosureAuthenticationException extends RuntimeException {}

final class InvalidClosureRequestException extends RuntimeException {
    InvalidClosureRequestException(String message) {
        super(message);
    }
}

final class ClosureTicketNotFoundException extends RuntimeException {}

final class CustomerMessageIdentityConflictException extends RuntimeException {}

final class TicketNotReplyableException extends RuntimeException {}
