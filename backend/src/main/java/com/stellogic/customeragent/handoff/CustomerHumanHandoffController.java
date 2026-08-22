package com.stellogic.customeragent.handoff;

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
@RequestMapping("/api/customer/tickets/{ticketId}")
public final class CustomerHumanHandoffController {
    private final HumanHandoffService service;

    CustomerHumanHandoffController(HumanHandoffService service) {
        this.service = service;
    }

    @PostMapping("/human-handoff")
    ResponseEntity<HumanHandoffResult> request(
            Authentication authentication,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID ticketId,
            @RequestBody HumanHandoffRequest body) {
        String owner = authentication.getName();
        requireText(requestId, "missing stable handoff identity");
        requireText(body.reasonCode(), "missing handoff reason");
        HumanHandoffResult result =
                service.request(
                        new RequestHumanHandoff(
                                owner, ticketId, requestId.trim(), body.reasonCode().trim()));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.ACCEPTED)
                .body(result);
    }

    @GetMapping("/human-handoff-requests/{requestId}")
    HumanHandoffResult status(
            Authentication authentication,
            @PathVariable UUID ticketId,
            @PathVariable String requestId) {
        requireText(requestId, "missing stable handoff identity");
        return service.status(authentication.getName(), ticketId, requestId.trim());
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank() || value.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
        }
    }

    record HumanHandoffRequest(String reasonCode) {}
}
