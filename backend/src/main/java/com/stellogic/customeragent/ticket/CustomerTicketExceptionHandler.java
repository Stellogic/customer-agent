package com.stellogic.customeragent.ticket;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public final class CustomerTicketExceptionHandler {
    @ExceptionHandler(IntakeRequestIdentityConflictException.class)
    ResponseEntity<CustomerIntakeV2Controller.IntakeResponse> intakeConflict(
            IntakeRequestIdentityConflictException exception) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(
                        CustomerIntakeV2Controller.IntakeResponse.from(
                                exception.authoritativeSnapshot()));
    }

    @ExceptionHandler(RequestIdentityConflictException.class)
    ResponseEntity<Map<String, String>> conflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "REQUEST_ID_CONFLICT", "message", "请求身份已用于不同参数"));
    }

    @ExceptionHandler(TicketNotFoundException.class)
    ResponseEntity<Map<String, String>> notFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("code", "TICKET_NOT_FOUND", "message", "客服工单不存在"));
    }

    @ExceptionHandler(InvalidCustomerRequestException.class)
    ResponseEntity<Map<String, String>> invalid(InvalidCustomerRequestException exception) {
        return ResponseEntity.badRequest()
                .body(Map.of("code", "INVALID_REQUEST", "message", exception.getMessage()));
    }

    @ExceptionHandler(CustomerAuthenticationException.class)
    ResponseEntity<Map<String, String>> unauthenticated() {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(Map.of("code", "CUSTOMER_AUTHENTICATION_REQUIRED", "message", "需要合成客户身份"));
    }

    @ExceptionHandler(ProjectionCursorException.class)
    ResponseEntity<Map<String, String>> cursorConflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "SNAPSHOT_REQUIRED", "message", "游标不兼容，请重新读取权威快照"));
    }

    @ExceptionHandler(IncompatibleCustomerSchemaException.class)
    ResponseEntity<Map<String, String>> incompatibleSchema() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "INCOMPATIBLE_SCHEMA", "message", "请求的公开沟通版本不兼容"));
    }

    @ExceptionHandler(CustomerMessageNotAcceptedException.class)
    ResponseEntity<Map<String, String>> messageNotAccepted() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "MESSAGE_NOT_ACCEPTED", "message", "当前工单不接受 Agent 对话回复"));
    }

    @ExceptionHandler(IntakeNotFoundException.class)
    ResponseEntity<Map<String, String>> intakeNotFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("code", "INTAKE_NOT_FOUND", "message", "受理对话不存在"));
    }

    @ExceptionHandler(IntakeNotReadyException.class)
    ResponseEntity<Map<String, String>> intakeNotReady() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "INTAKE_NOT_READY", "message", "请先确认订单与问题理解"));
    }

    @ExceptionHandler(IntakeCandidateStaleException.class)
    ResponseEntity<Map<String, String>> intakeCandidateStale() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "INTAKE_CANDIDATE_STALE", "message", "订单事实已变化，请重新确认"));
    }

    @ExceptionHandler(IntakeArchivedException.class)
    ResponseEntity<Map<String, String>> intakeArchived() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "INTAKE_ARCHIVED", "message", "受理对话已归档，请先恢复并重新确认事实"));
    }

    @ExceptionHandler(IntakeVersionConflictException.class)
    ResponseEntity<Map<String, String>> intakeVersionConflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "INTAKE_VERSION_CONFLICT", "message", "受理版本已变化，请重新读取权威记录"));
    }

    @ExceptionHandler(IntakeAgentUnavailableException.class)
    ResponseEntity<Map<String, String>> intakeAgentUnavailable() {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(Map.of("code", "INTAKE_AGENT_UNAVAILABLE", "message", "受理理解暂时不可用，请稍后重试"));
    }
}
