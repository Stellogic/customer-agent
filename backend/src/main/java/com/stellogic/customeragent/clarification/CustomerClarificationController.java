package com.stellogic.customeragent.clarification;

import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/customer/v2/tickets/{ticketId}")
final class CustomerClarificationController {
    private final ClarificationService service;

    CustomerClarificationController(ClarificationService service) {
        this.service = service;
    }

    @PostMapping("/clarifications/{clarificationRequestId}/replies")
    ResponseEntity<ClarificationReplyResult> reply(
            Authentication authentication,
            @RequestHeader(value = "Idempotency-Key", required = false) String customerMessageId,
            @RequestHeader(value = "X-Resume-Request-Id", required = false) UUID resumeRequestId,
            @PathVariable UUID ticketId,
            @PathVariable UUID clarificationRequestId,
            @RequestBody ReplyBody body) {
        String owner = authentication.getName();
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
            Authentication authentication,
            @PathVariable UUID ticketId,
            @PathVariable UUID resumeRequestId) {
        return service.status(authentication.getName(), ticketId, resumeRequestId);
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank() || value.length() > 2000) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
        }
    }

    record ReplyBody(String answer) {}
}
