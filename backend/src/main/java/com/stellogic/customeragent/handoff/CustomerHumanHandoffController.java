package com.stellogic.customeragent.handoff;

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
public final class CustomerHumanHandoffController {
    private static final Set<String> SYNTHETIC_CUSTOMERS = Set.of("customer-demo", "customer-other-demo");
    private final HumanHandoffService service;

    CustomerHumanHandoffController(HumanHandoffService service) {
        this.service = service;
    }

    @PostMapping("/human-handoff")
    ResponseEntity<HumanHandoffResult> request(
            @RequestHeader(value = "X-Synthetic-Customer-Id", required = false) String customerId,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID ticketId,
            @RequestBody HumanHandoffRequest body) {
        String owner = requireCustomer(customerId);
        requireText(requestId, "missing stable handoff identity");
        requireText(body.reasonCode(), "missing handoff reason");
        HumanHandoffResult result = service.request(new RequestHumanHandoff(
                owner, ticketId, requestId.trim(), body.reasonCode().trim()));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.ACCEPTED).body(result);
    }

    @GetMapping("/human-handoff-requests/{requestId}")
    HumanHandoffResult status(
            @RequestHeader(value = "X-Synthetic-Customer-Id", required = false) String customerId,
            @PathVariable UUID ticketId,
            @PathVariable String requestId) {
        requireText(requestId, "missing stable handoff identity");
        return service.status(requireCustomer(customerId), ticketId, requestId.trim());
    }

    private static String requireCustomer(String customerId) {
        if (customerId == null || !SYNTHETIC_CUSTOMERS.contains(customerId.trim())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "customer identity required");
        }
        return customerId.trim();
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank() || value.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
        }
    }

    record HumanHandoffRequest(String reasonCode) {}
}
