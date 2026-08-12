package com.stellogic.customeragent.clarification;

import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/customer/tickets/{ticketId}")
final class CustomerClarificationController {
    private static final Set<String> SYNTHETIC_CUSTOMERS =
            Set.of("customer-demo", "customer-other-demo");
    private final ClarificationService service;

    CustomerClarificationController(ClarificationService service) {
        this.service = service;
    }

    @PostMapping("/clarifications/{clarificationRequestId}/replies")
    ResponseEntity<ClarificationReplyResult> reply(
            @RequestHeader(value = "X-Synthetic-Customer-Id", required = false) String customerId,
            @RequestHeader(value = "Idempotency-Key", required = false) String customerMessageId,
            @RequestHeader(value = "X-Resume-Request-Id", required = false) UUID resumeRequestId,
            @PathVariable UUID ticketId,
            @PathVariable UUID clarificationRequestId,
            @RequestBody ReplyBody body) {
        String owner = requireIdentity(customerId);
        requireText(customerMessageId, "missing stable customer message identity");
        if (resumeRequestId == null)
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "missing resume request identity");
        requireText(body.answer(), "missing clarification answer");
        ClarificationReplyResult result =
                service.reply(
                        new ReplyToClarification(
                                owner,
                                ticketId,
                                clarificationRequestId,
                                customerMessageId.trim(),
                                resumeRequestId,
                                body.answer().trim()));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.ACCEPTED)
                .body(result);
    }

    @GetMapping("/clarification-resumes/{resumeRequestId}")
    ClarificationReplyResult status(
            @RequestHeader(value = "X-Synthetic-Customer-Id", required = false) String customerId,
            @PathVariable UUID ticketId,
            @PathVariable UUID resumeRequestId) {
        return service.status(requireIdentity(customerId), ticketId, resumeRequestId);
    }

    private static String requireIdentity(String customerId) {
        if (customerId == null || !SYNTHETIC_CUSTOMERS.contains(customerId.trim())) {
            throw new ResponseStatusException(
                    HttpStatus.UNAUTHORIZED, "customer identity required");
        }
        return customerId.trim();
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank() || value.length() > 2000) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
        }
    }

    record ReplyBody(String answer) {}
}
