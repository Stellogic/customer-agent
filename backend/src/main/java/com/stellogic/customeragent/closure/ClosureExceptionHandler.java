package com.stellogic.customeragent.closure;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
final class ClosureExceptionHandler {
    @ExceptionHandler(ClosureAuthenticationException.class)
    ResponseEntity<Map<String, String>> unauthenticated() {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(Map.of("code", "CUSTOMER_AUTHENTICATION_REQUIRED", "message", "需要合成客户身份"));
    }

    @ExceptionHandler(InvalidClosureRequestException.class)
    ResponseEntity<Map<String, String>> invalid(InvalidClosureRequestException exception) {
        return ResponseEntity.badRequest()
                .body(Map.of("code", "INVALID_REQUEST", "message", exception.getMessage()));
    }

    @ExceptionHandler(ClosureTicketNotFoundException.class)
    ResponseEntity<Map<String, String>> notFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("code", "TICKET_NOT_FOUND", "message", "客服工单不存在"));
    }

    @ExceptionHandler(CustomerMessageIdentityConflictException.class)
    ResponseEntity<Map<String, String>> identityConflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "MESSAGE_ID_CONFLICT", "message", "消息身份已用于不同参数"));
    }

    @ExceptionHandler(TicketNotReplyableException.class)
    ResponseEntity<Map<String, String>> notReplyable() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "TICKET_NOT_REPLYABLE", "message", "当前客服工单不在关闭等待期或已关闭"));
    }
}
