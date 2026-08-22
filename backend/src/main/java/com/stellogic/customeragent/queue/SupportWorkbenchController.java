package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import java.util.List;
import java.util.UUID;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/support/workbench")
public final class SupportWorkbenchController {
    private final SupportWorkbenchProjectionService service;

    SupportWorkbenchController(SupportWorkbenchProjectionService service) {
        this.service = service;
    }

    @GetMapping("/snapshot")
    ResponseEntity<SnapshotResponse> snapshot(Authentication authentication) {
        String supportId = authentication.getName();
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(SnapshotResponse.from(service.snapshot(supportId)));
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

    @GetMapping(value = "/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter events(
            Authentication authentication,
            @RequestHeader(value = "Last-Event-ID", required = false) String cursor) {
        String support = authentication.getName();
        return AuthorizedSsePollingStream.open(
                "support-workbench-events",
                250,
                AuthorizedSsePollingStream.MAX_AUTHORIZATION_STALENESS_MILLIS,
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
