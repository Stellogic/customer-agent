package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import jakarta.servlet.http.HttpServletRequest;
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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/support/workbench")
public final class SupportWorkbenchController {
    private final SupportWorkbenchProjectionService service;

    SupportWorkbenchController(SupportWorkbenchProjectionService service) {
        this.service = service;
    }

    @GetMapping("/snapshot")
    ResponseEntity<?> snapshot(
            Authentication authentication,
            @RequestParam(
                            value = "schema",
                            defaultValue = SupportWorkbenchProjectionService.LEGACY_EPOCH)
                    String schema) {
        String supportId = authentication.getName();
        SupportWorkbenchSnapshot snapshot = service.snapshot(supportId, schema);
        Object response =
                SupportWorkbenchProjectionService.LEGACY_EPOCH.equals(snapshot.epoch())
                        ? LegacySnapshotResponse.from(snapshot)
                        : SnapshotResponse.from(snapshot);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(response);
    }

    @GetMapping("/tickets/{ticketId}")
    ResponseEntity<SupportTicketDetails> details(
            Authentication authentication, @PathVariable UUID ticketId) {
        String supportId = authentication.getName();
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.details(supportId, ticketId));
    }

    @PostMapping("/tickets/{ticketId}/claims")
    ResponseEntity<SupportAssignmentClaim> claim(
            Authentication authentication, @PathVariable UUID ticketId) {
        SupportAssignmentClaim claim = service.claim(authentication.getName(), ticketId);
        return ResponseEntity.status(claim.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(claim);
    }

    @PostMapping("/tickets/{ticketId}/messages")
    ResponseEntity<PublicReplyResponse> publicReply(
            Authentication authentication,
            @PathVariable UUID ticketId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> request) {
        String normalizedIdempotencyKey = requireIdempotencyKey(idempotencyKey);
        String body = requireReplyBody(request);
        SupportPublicReplyResult result =
                service.publicReply(
                        authentication.getName(), ticketId, normalizedIdempotencyKey, body);
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .cacheControl(CacheControl.noStore())
                .body(PublicReplyResponse.from(result));
    }

    @GetMapping("/tickets/{ticketId}/messages/{messageId}")
    ResponseEntity<PublicReplyResponse> publicReplyResult(
            Authentication authentication,
            @PathVariable UUID ticketId,
            @PathVariable String messageId) {
        SupportPublicReplyResult result =
                service.queryPublicReply(
                        authentication.getName(), ticketId, requireIdempotencyKey(messageId));
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(PublicReplyResponse.from(result));
    }

    @GetMapping(value = "/tickets/{ticketId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter assignedTicketEvents(
            Authentication authentication,
            @PathVariable UUID ticketId,
            HttpServletRequest request) {
        String support = authentication.getName();
        return AuthorizedSsePollingStream.open(
                "support-ticket-authority-" + ticketId,
                250,
                AuthorizedSsePollingStream.MAX_AUTHORIZATION_STALENESS_MILLIS,
                null,
                AuthorizedSsePollingStream.requireCurrentHttpSession(
                        request,
                        support,
                        new AuthorizedSsePollingStream.Source<Object>() {
                            @Override
                            public List<Object> events(String ignoredCursor) {
                                service.details(support, ticketId);
                                return List.of();
                            }

                            @Override
                            public void authorize() {
                                service.details(support, ticketId);
                            }

                            @Override
                            public String cursor(Object ignoredEvent) {
                                throw new IllegalStateException(
                                        "authority stream does not emit events");
                            }

                            @Override
                            public SseEmitter.SseEventBuilder render(Object ignoredEvent) {
                                throw new IllegalStateException(
                                        "authority stream does not emit events");
                            }
                        }));
    }

    @GetMapping(value = "/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter events(
            Authentication authentication,
            HttpServletRequest request,
            @RequestHeader(value = "Last-Event-ID", required = false) String cursor) {
        String support = authentication.getName();
        return AuthorizedSsePollingStream.open(
                "support-workbench-events",
                250,
                AuthorizedSsePollingStream.MAX_AUTHORIZATION_STALENESS_MILLIS,
                cursor,
                AuthorizedSsePollingStream.requireCurrentHttpSession(
                        request,
                        support,
                        new AuthorizedSsePollingStream.Source<SupportWorkbenchEvent>() {
                            @Override
                            public List<SupportWorkbenchEvent> events(String afterCursor) {
                                return service.events(support, afterCursor);
                            }

                            @Override
                            public void authorize() {
                                service.snapshot(support);
                            }

                            @Override
                            public String cursor(SupportWorkbenchEvent event) {
                                return event.cursor();
                            }

                            @Override
                            public SseEmitter.SseEventBuilder render(SupportWorkbenchEvent event) {
                                return SseEmitter.event()
                                        .id(event.cursor())
                                        .name(event.type())
                                        .data(event.publicData());
                            }
                        }));
    }

    record SnapshotResponse(
            String view,
            String schema,
            String cursor,
            List<?> sharedQueue,
            List<?> escalationQueue,
            UUID assignedTicketId) {
        static SnapshotResponse from(SupportWorkbenchSnapshot snapshot) {
            return new SnapshotResponse(
                    "SUPPORT_WORKBENCH",
                    snapshot.epoch(),
                    snapshot.epoch() + ":" + snapshot.sequence(),
                    snapshot.sharedQueue(),
                    snapshot.escalationQueue(),
                    snapshot.assignedTicketId());
        }
    }

    record LegacySnapshotResponse(
            String view,
            String schema,
            String cursor,
            List<LegacyQueueItem> sharedQueue,
            List<LegacyQueueItem> escalationQueue) {
        static LegacySnapshotResponse from(SupportWorkbenchSnapshot snapshot) {
            return new LegacySnapshotResponse(
                    "SUPPORT_WORKBENCH",
                    snapshot.epoch(),
                    snapshot.epoch() + ":" + snapshot.sequence(),
                    legacyItems(snapshot.sharedQueue()),
                    legacyItems(snapshot.escalationQueue()));
        }
    }

    record LegacyQueueItem(
            UUID ticketId,
            SupportTicketLifecycleState lifecycleState,
            SupportHandlingMode handlingMode,
            java.time.Instant enteredAt) {
        static LegacyQueueItem from(SupportQueueItem item) {
            return new LegacyQueueItem(
                    item.ticketId(), item.lifecycleState(), item.handlingMode(), item.enteredAt());
        }
    }

    record PublicReplyResponse(
            String schema,
            UUID ticketId,
            String messageId,
            UUID publicMessageId,
            String outcome,
            boolean accepted,
            boolean replayed) {
        static PublicReplyResponse from(SupportPublicReplyResult result) {
            return new PublicReplyResponse(
                    SupportWorkbenchProjectionService.EPOCH,
                    result.ticketId(),
                    result.messageId(),
                    result.publicMessageId(),
                    result.outcome(),
                    true,
                    result.replayed());
        }
    }

    private static String requireIdempotencyKey(String idempotencyKey) {
        if (idempotencyKey == null
                || idempotencyKey.isBlank()
                || idempotencyKey.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Idempotency-Key 无效");
        }
        return idempotencyKey.trim();
    }

    private static String requireReplyBody(Map<String, Object> request) {
        if (request == null
                || !request.keySet().equals(Set.of("schema", "message"))
                || !SupportWorkbenchProjectionService.EPOCH.equals(request.get("schema"))
                || !(request.get("message") instanceof String)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "公开回复请求格式无效");
        }
        String body = ((String) request.get("message")).trim();
        if (body.isEmpty() || body.length() > 2000) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "公开回复内容长度无效");
        }
        return body;
    }

    private static List<LegacyQueueItem> legacyItems(List<SupportQueueItem> items) {
        return items.stream().map(LegacyQueueItem::from).toList();
    }
}
