package com.stellogic.customeragent.queue;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public final class SupportWorkbenchExceptionHandler {
    @ExceptionHandler(SupportIdentityRequiredException.class)
    ResponseEntity<Map<String, String>> forbidden() {
        return ResponseEntity.status(HttpStatus.FORBIDDEN)
                .body(Map.of("code", "SUPPORT_IDENTITY_REQUIRED", "message", "需要合成客服身份"));
    }

    @ExceptionHandler(SupportWorkbenchCursorException.class)
    ResponseEntity<Map<String, String>> cursorConflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "SNAPSHOT_REQUIRED", "message", "游标不兼容，请重新读取客服工作台权威快照"));
    }

    @ExceptionHandler(SupportTicketNotFoundException.class)
    ResponseEntity<Map<String, String>> ticketNotFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .header("Cache-Control", "no-store")
                .body(Map.of("code", "SUPPORT_TICKET_NOT_FOUND", "message", "客服工单不存在"));
    }
}
