package com.stellogic.customeragent.ticket;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public final class IntakeAssistanceExceptionHandler {
    @ExceptionHandler(IntakeAssistanceNotFoundException.class)
    ResponseEntity<Map<String, String>> notFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("code", "INTAKE_ASSISTANCE_NOT_FOUND", "message", "受理协助责任不存在或已失效"));
    }

    @ExceptionHandler(IntakeAssistanceConflictException.class)
    ResponseEntity<Map<String, String>> conflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "INTAKE_ASSISTANCE_CONFLICT", "message", "受理协助状态或请求身份已变化"));
    }

    @ExceptionHandler(IntakeAssistanceCursorException.class)
    ResponseEntity<Map<String, String>> cursor() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "SNAPSHOT_REQUIRED", "message", "游标不兼容，请重新读取权威快照"));
    }
}
