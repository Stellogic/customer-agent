package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.identity.SyntheticIdentityController;
import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import java.util.List;
import java.util.UUID;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/support/workbench")
public final class SupportWorkbenchController {
    private static final String SUPPORT_HEADER = "X-Synthetic-Support-Id";
    private final SupportWorkbenchProjectionService service;

    SupportWorkbenchController(SupportWorkbenchProjectionService service) {
        this.service = service;
    }

    @GetMapping("/snapshot")
    ResponseEntity<SnapshotResponse> snapshot(
            @RequestHeader(value = SUPPORT_HEADER, required = false) String supportHeader,
            @CookieValue(value = SyntheticIdentityController.SESSION_COOKIE, required = false)
                    String sessionId) {
        String supportId = resolveSupportId(supportHeader, sessionId);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(SnapshotResponse.from(service.snapshot(supportId)));
    }

    @GetMapping("/tickets/{ticketId}")
    ResponseEntity<SupportTicketDetails> details(
            @RequestHeader(value = SUPPORT_HEADER, required = false) String supportHeader,
            @CookieValue(value = SyntheticIdentityController.SESSION_COOKIE, required = false)
                    String sessionId,
            @PathVariable UUID ticketId) {
        String supportId = resolveSupportId(supportHeader, sessionId);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.details(supportId, ticketId));
    }

    @GetMapping(value = "/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter events(
            @RequestHeader(value = SUPPORT_HEADER, required = false) String supportHeader,
            @CookieValue(value = SyntheticIdentityController.SESSION_COOKIE, required = false)
                    String sessionId,
            @RequestHeader(value = "Last-Event-ID", required = false) String cursor) {
        String support = resolveSupportId(supportHeader, sessionId);
        return AuthorizedSsePollingStream.open(
                "support-workbench-events",
                250,
                60_000L,
                cursor,
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
                });
    }

    private static String resolveSupportId(String supportHeader, String sessionId) {
        String supportId =
                supportHeader == null || supportHeader.isBlank() ? sessionId : supportHeader.trim();
        SupportWorkbenchProjectionService.requireSupport(supportId);
        return supportId;
    }

    record SnapshotResponse(
            String view,
            String schema,
            String cursor,
            List<SupportQueueItem> sharedQueue,
            List<SupportQueueItem> escalationQueue) {
        static SnapshotResponse from(SupportWorkbenchSnapshot snapshot) {
            return new SnapshotResponse(
                    "SUPPORT_WORKBENCH",
                    snapshot.epoch(),
                    snapshot.epoch() + ":" + snapshot.sequence(),
                    snapshot.sharedQueue(),
                    snapshot.escalationQueue());
        }
    }
}
