package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import jakarta.servlet.http.HttpServletRequest;
import java.math.BigInteger;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/support/intake-assistance")
public final class IntakeAssistanceController {
    private static final Set<String> PROPOSAL_FIELDS =
            Set.of("schema", "expectedIntakeVersion", "orderReference", "issues");
    private static final Set<String> ISSUE_FIELDS = Set.of("kind", "summary");
    private final IntakeAssistanceService service;

    IntakeAssistanceController(IntakeAssistanceService service) {
        this.service = service;
    }

    @GetMapping("/snapshot")
    ResponseEntity<SnapshotResponse> snapshot(Authentication authentication) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(SnapshotResponse.from(service.snapshot(authentication.getName())));
    }

    @GetMapping("/requests/{requestId}")
    ResponseEntity<IntakeAssistanceDetails> details(
            Authentication authentication, @PathVariable UUID requestId) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.details(authentication.getName(), requestId));
    }

    @PostMapping("/requests/{requestId}/claims")
    ResponseEntity<IntakeAssistanceClaim> claim(
            Authentication authentication, @PathVariable UUID requestId) {
        IntakeAssistanceClaim claim = service.claim(authentication.getName(), requestId);
        return ResponseEntity.status(claim.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(claim);
    }

    @PostMapping("/requests/{requestId}/release")
    IntakeAssistanceMutation release(Authentication authentication, @PathVariable UUID requestId) {
        return service.release(authentication.getName(), requestId);
    }

    @PostMapping("/requests/{requestId}/proposal")
    ResponseEntity<IntakeAssistanceMutation> propose(
            Authentication authentication,
            @PathVariable UUID requestId,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestKey,
            @RequestBody Map<String, Object> request) {
        if (!request.keySet().equals(PROPOSAL_FIELDS)
                || !IntakeAssistanceService.EPOCH.equals(request.get("schema"))) {
            throw new InvalidCustomerRequestException("受理协助修正字段与版本无效");
        }
        Object rawIssues = request.get("issues");
        if (!(rawIssues instanceof List<?> issueValues)) {
            throw new InvalidCustomerRequestException("拟建问题无效");
        }
        List<ProposedIntakeIssue> issues =
                issueValues.stream().map(IntakeAssistanceController::parseIssue).toList();
        IntakeAssistanceMutation result =
                service.propose(
                        new IntakeAssistanceProposalCommand(
                                authentication.getName(),
                                requestId,
                                requireText(requestKey, 200, "缺少稳定请求身份"),
                                requirePositiveLong(request.get("expectedIntakeVersion")),
                                requireText(request.get("orderReference"), 200, "请选择订单候选"),
                                issues));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(result);
    }

    @GetMapping(value = "/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter events(
            Authentication authentication,
            HttpServletRequest request,
            @RequestHeader(value = "Last-Event-ID", required = false) String cursor) {
        String support = authentication.getName();
        return AuthorizedSsePollingStream.open(
                "intake-assistance-events",
                250,
                AuthorizedSsePollingStream.MAX_AUTHORIZATION_STALENESS_MILLIS,
                cursor,
                AuthorizedSsePollingStream.requireCurrentHttpSession(
                        request,
                        support,
                        new AuthorizedSsePollingStream.Source<IntakeAssistanceEvent>() {
                            @Override
                            public List<IntakeAssistanceEvent> events(String afterCursor) {
                                return service.events(support, afterCursor);
                            }

                            @Override
                            public void authorize() {
                                service.snapshot(support);
                            }

                            @Override
                            public String cursor(IntakeAssistanceEvent event) {
                                return event.cursor();
                            }

                            @Override
                            public SseEmitter.SseEventBuilder render(IntakeAssistanceEvent event) {
                                return SseEmitter.event()
                                        .id(event.cursor())
                                        .name(event.type())
                                        .data(event.publicData());
                            }
                        }));
    }

    @GetMapping(
            value = "/requests/{requestId}/events",
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter authorityEvents(
            Authentication authentication,
            @PathVariable UUID requestId,
            HttpServletRequest request) {
        String support = authentication.getName();
        return AuthorizedSsePollingStream.open(
                "intake-assistance-authority-" + requestId,
                250,
                AuthorizedSsePollingStream.MAX_AUTHORIZATION_STALENESS_MILLIS,
                null,
                AuthorizedSsePollingStream.requireCurrentHttpSession(
                        request,
                        support,
                        new AuthorizedSsePollingStream.Source<Object>() {
                            @Override
                            public List<Object> events(String ignoredCursor) {
                                service.details(support, requestId);
                                return List.of();
                            }

                            @Override
                            public void authorize() {
                                service.details(support, requestId);
                            }

                            @Override
                            public String cursor(Object ignoredEvent) {
                                throw new IllegalStateException("authority stream has no events");
                            }

                            @Override
                            public SseEmitter.SseEventBuilder render(Object ignoredEvent) {
                                throw new IllegalStateException("authority stream has no events");
                            }
                        }));
    }

    private static ProposedIntakeIssue parseIssue(Object value) {
        if (!(value instanceof Map<?, ?> map) || !map.keySet().equals(ISSUE_FIELDS)) {
            throw new InvalidCustomerRequestException("拟建问题无效");
        }
        return new ProposedIntakeIssue(
                requireText(map.get("kind"), 80, "问题类型无效"),
                requireText(map.get("summary"), 500, "问题摘要无效"));
    }

    private static long requirePositiveLong(Object value) {
        BigInteger integer =
                switch (value) {
                    case Byte number -> BigInteger.valueOf(number.longValue());
                    case Short number -> BigInteger.valueOf(number.longValue());
                    case Integer number -> BigInteger.valueOf(number.longValue());
                    case Long number -> BigInteger.valueOf(number);
                    case BigInteger number -> number;
                    default -> throw new InvalidCustomerRequestException("受理版本无效");
                };
        if (integer.signum() <= 0 || integer.bitLength() > 63) {
            throw new InvalidCustomerRequestException("受理版本无效");
        }
        return integer.longValueExact();
    }

    private static String requireText(Object value, int maximum, String message) {
        if (!(value instanceof String text) || text.isBlank() || text.length() > maximum) {
            throw new InvalidCustomerRequestException(message);
        }
        return text.trim();
    }

    record SnapshotResponse(
            String view, String schema, String cursor, List<IntakeAssistanceQueueItem> requests) {
        static SnapshotResponse from(IntakeAssistanceSnapshot snapshot) {
            return new SnapshotResponse(
                    "INTAKE_ASSISTANCE",
                    snapshot.epoch(),
                    snapshot.epoch() + ":" + snapshot.sequence(),
                    snapshot.requests());
        }
    }
}
