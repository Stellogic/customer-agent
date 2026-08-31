package com.stellogic.customeragent.queue;

import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.CacheControl;
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
@RequestMapping("/api/support/workbench/tickets/{ticketId}")
public final class SupportCompensationController {
    private static final Set<String> PROPOSAL_FIELDS = Set.of("schema", "planCode", "reasonCode");
    private static final Set<String> EXCEPTION_FIELDS =
            Set.of("schema", "reasonCode", "justification");
    private final SupportCompensationService service;

    SupportCompensationController(SupportCompensationService service) {
        this.service = service;
    }

    @GetMapping("/compensation-options")
    ResponseEntity<SupportCompensationOptions> options(
            Authentication authentication, @PathVariable UUID ticketId) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.listOptions(authentication.getName(), ticketId));
    }

    @PostMapping("/compensation-proposals")
    ResponseEntity<SupportCompensationProposalResult> submitProposal(
            Authentication authentication,
            @PathVariable UUID ticketId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> request) {
        rejectAmountOverride(request);
        requireExactFields(request, PROPOSAL_FIELDS);
        requireSchema(request);
        SupportCompensationProposalResult result =
                service.submitProposal(
                        authentication.getName(),
                        ticketId,
                        requireText(request, "planCode"),
                        requireText(request, "reasonCode"),
                        requireIdempotencyKey(idempotencyKey));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .cacheControl(CacheControl.noStore())
                .body(result);
    }

    @GetMapping("/compensation-proposals/{requestId}")
    ResponseEntity<SupportCompensationProposalResult> queryProposal(
            Authentication authentication,
            @PathVariable UUID ticketId,
            @PathVariable String requestId) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(
                        service.queryProposal(
                                authentication.getName(),
                                ticketId,
                                requireIdempotencyKey(requestId)));
    }

    @PostMapping("/exceptional-compensation-requests")
    ResponseEntity<SupportExceptionalCompensationResult> submitException(
            Authentication authentication,
            @PathVariable UUID ticketId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> request) {
        rejectAmountOverride(request);
        requireExactFields(request, EXCEPTION_FIELDS);
        requireSchema(request);
        String justification = requireText(request, "justification");
        if (justification.length() > 2000) {
            throw new SupportCompensationInvalidRequestException("INVALID_REQUEST");
        }
        SupportExceptionalCompensationResult result =
                service.submitException(
                        authentication.getName(),
                        ticketId,
                        requireText(request, "reasonCode"),
                        justification,
                        requireIdempotencyKey(idempotencyKey));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .cacheControl(CacheControl.noStore())
                .body(result);
    }

    @GetMapping("/exceptional-compensation-requests/{requestId}")
    ResponseEntity<SupportExceptionalCompensationResult> queryException(
            Authentication authentication,
            @PathVariable UUID ticketId,
            @PathVariable String requestId) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(
                        service.queryException(
                                authentication.getName(),
                                ticketId,
                                requireIdempotencyKey(requestId)));
    }

    private static void rejectAmountOverride(Map<String, Object> request) {
        if (request != null
                && (request.containsKey("amount")
                        || request.containsKey("compensationMethod")
                        || request.containsKey("capAmount"))) {
            throw new SupportCompensationInvalidRequestException("AMOUNT_OVERRIDE_FORBIDDEN");
        }
    }

    private static void requireExactFields(Map<String, Object> request, Set<String> fields) {
        if (request == null || !request.keySet().equals(fields)) {
            throw new SupportCompensationInvalidRequestException("INVALID_REQUEST");
        }
    }

    private static void requireSchema(Map<String, Object> request) {
        if (!SupportCompensationService.SCHEMA.equals(request.get("schema"))) {
            throw new SupportCompensationInvalidRequestException("INVALID_REQUEST");
        }
    }

    private static String requireText(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof String text) || text.isBlank()) {
            throw new SupportCompensationInvalidRequestException("INVALID_REQUEST");
        }
        return text.trim();
    }

    private static String requireIdempotencyKey(String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.isBlank() || idempotencyKey.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Idempotency-Key 无效");
        }
        return idempotencyKey.trim();
    }
}
