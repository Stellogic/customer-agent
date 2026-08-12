package com.stellogic.customeragent.closure;

import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/customer/tickets")
public final class CustomerReplyController {
    private static final Set<String> SYNTHETIC_CUSTOMERS =
            Set.of("customer-demo", "customer-other-demo");
    private static final Set<String> ISSUE_KINDS = Set.of("LOGISTICS_DELAY", "OTHER");
    private final ClosureService service;

    public CustomerReplyController(ClosureService service) {
        this.service = service;
    }

    @PostMapping("/{ticketId}/replies")
    ResponseEntity<ReplyResponse> reply(
            @RequestHeader(value = "X-Synthetic-Customer-Id", required = false) String customerId,
            @RequestHeader(value = "Idempotency-Key", required = false) String messageId,
            @PathVariable UUID ticketId,
            @RequestBody ReplyRequest request) {
        if (customerId == null || !SYNTHETIC_CUSTOMERS.contains(customerId.trim())) {
            throw new ClosureAuthenticationException();
        }
        requireText(messageId, "缺少稳定消息身份");
        requireText(request.orderReference(), "缺少订单编号");
        requireText(request.issueKind(), "缺少问题类型");
        if (!ISSUE_KINDS.contains(request.issueKind().trim())) {
            throw new InvalidClosureRequestException("不支持的问题类型");
        }
        requireText(request.message(), "缺少客户回复");
        CustomerReplyResult result =
                service.reply(
                        new CustomerReplyCommand(
                                customerId.trim(),
                                ticketId,
                                messageId.trim(),
                                request.orderReference().trim(),
                                request.issueKind().trim(),
                                request.message().trim()));
        HttpStatus status =
                "LINKED_TICKET_CREATED".equals(result.outcome()) && !result.replayed()
                        ? HttpStatus.CREATED
                        : HttpStatus.OK;
        return ResponseEntity.status(status)
                .body(new ReplyResponse(result.ticketId(), result.outcome(), result.replayed()));
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank() || value.length() > 2000) {
            throw new InvalidClosureRequestException(message);
        }
    }

    record ReplyRequest(String orderReference, String issueKind, String message) {}

    record ReplyResponse(UUID ticketId, String outcome, boolean replayed) {}
}
