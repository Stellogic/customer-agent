package com.stellogic.customeragent.queue;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
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
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("code", "SNAPSHOT_REQUIRED", "message", "游标不兼容，请重新读取客服工作台权威快照"));
    }

    @ExceptionHandler(SupportTicketNotFoundException.class)
    ResponseEntity<Map<String, String>> ticketNotFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .header("Cache-Control", "no-store")
                .body(Map.of("code", "SUPPORT_TICKET_NOT_FOUND", "message", "客服工单不存在"));
    }

    @ExceptionHandler(SupportPublicReplyNotAllowedException.class)
    ResponseEntity<Map<String, String>> publicReplyNotAllowed() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .header("Cache-Control", "no-store")
                .body(
                        Map.of(
                                "code",
                                "SUPPORT_REPLY_NOT_ALLOWED",
                                "message",
                                "只有人工处理中的当前负责客服可以发送公开回复"));
    }

    @ExceptionHandler(SupportReplyIdentityConflictException.class)
    ResponseEntity<Map<String, String>> replyIdentityConflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .header("Cache-Control", "no-store")
                .body(
                        Map.of(
                                "code",
                                "SUPPORT_REPLY_IDENTITY_CONFLICT",
                                "message",
                                "同一幂等键已绑定其他公开回复内容"));
    }

    @ExceptionHandler(SupportCompensationNotAllowedException.class)
    ResponseEntity<Map<String, String>> compensationNotAllowed(
            SupportCompensationNotAllowedException exception) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .header("Cache-Control", "no-store")
                .body(Map.of("code", exception.code(), "message", "当前负责客服不能提交标准补偿，或处理模式已经变化"));
    }

    @ExceptionHandler(SupportCompensationConflictException.class)
    ResponseEntity<Map<String, String>> compensationConflict(
            SupportCompensationConflictException exception) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .header("Cache-Control", "no-store")
                .body(
                        Map.of(
                                "code",
                                exception.code(),
                                "message",
                                conflictMessage(exception.code())));
    }

    @ExceptionHandler(SupportCompensationInvalidRequestException.class)
    ResponseEntity<Map<String, String>> compensationInvalid(
            SupportCompensationInvalidRequestException exception) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .header("Cache-Control", "no-store")
                .body(
                        Map.of(
                                "code",
                                exception.code(),
                                "message",
                                "AMOUNT_OVERRIDE_FORBIDDEN".equals(exception.code())
                                        ? "不能提交任意金额或方式覆盖"
                                        : "标准补偿请求无效"));
    }

    @ExceptionHandler(SupportCompensationIdentityConflictException.class)
    ResponseEntity<Map<String, String>> compensationIdentityConflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .header("Cache-Control", "no-store")
                .body(
                        Map.of(
                                "code",
                                "SUPPORT_COMPENSATION_IDENTITY_CONFLICT",
                                "message",
                                "同一幂等键已绑定其他补偿提交内容"));
    }

    private static String conflictMessage(String code) {
        return switch (code) {
            case "COMPENSATION_ALLOWANCE_INSUFFICIENT" -> "剩余可补偿额度不足";
            case "STALE_COMPENSATION_FACTS" -> "订单事实或方案已变化，请重新读取标准补偿方案";
            case "COMPENSATION_PROPOSAL_INELIGIBLE" -> "当前订单不符合标准补偿资格";
            default -> "标准补偿提交未被接受，请根据权威结果恢复";
        };
    }
}
