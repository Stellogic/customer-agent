package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.identity.SyntheticIdentityController;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.CookieValue;
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
            @CookieValue(value = SyntheticIdentityController.SESSION_COOKIE, required = false) String sessionId) {
        String supportId = resolveSupportId(supportHeader, sessionId);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(SnapshotResponse.from(service.snapshot(supportId)));
    }

    @GetMapping("/tickets/{ticketId}")
    ResponseEntity<SupportTicketDetails> details(
            @RequestHeader(value = SUPPORT_HEADER, required = false) String supportHeader,
            @CookieValue(value = SyntheticIdentityController.SESSION_COOKIE, required = false) String sessionId,
            @PathVariable UUID ticketId) {
        String supportId = resolveSupportId(supportHeader, sessionId);
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.details(supportId, ticketId));
    }

    @GetMapping(value = "/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter events(
            @RequestHeader(value = SUPPORT_HEADER, required = false) String supportHeader,
            @CookieValue(value = SyntheticIdentityController.SESSION_COOKIE, required = false) String sessionId,
            @RequestHeader(value = "Last-Event-ID", required = false) String cursor) {
        String support = resolveSupportId(supportHeader, sessionId);
        List<SupportWorkbenchEvent> replay = service.events(support, cursor);
        SseEmitter emitter = new SseEmitter(60_000L);
        try {
            for (SupportWorkbenchEvent event : replay) sendAuthorized(emitter, support, event);
            emitter.send(SseEmitter.event().comment("connected"));
        } catch (Exception exception) {
            emitter.completeWithError(exception);
            return emitter;
        }
        String nextCursor = replay.isEmpty() ? cursor : replay.getLast().cursor();
        startIncrementalStream(emitter, support, nextCursor);
        return emitter;
    }

    private static String resolveSupportId(String supportHeader, String sessionId) {
        String supportId = supportHeader == null || supportHeader.isBlank() ? sessionId : supportHeader.trim();
        SupportWorkbenchProjectionService.requireSupport(supportId);
        return supportId;
    }

    private void startIncrementalStream(SseEmitter emitter, String supportId, String initialCursor) {
        AtomicBoolean closed = new AtomicBoolean();
        emitter.onCompletion(() -> closed.set(true));
        emitter.onTimeout(() -> {
            closed.set(true);
            emitter.complete();
        });
        emitter.onError(error -> closed.set(true));
        Thread.ofVirtual().name("support-workbench-events").start(() -> {
            String cursor = initialCursor;
            try {
                while (!closed.get()) {
                    Thread.sleep(250);
                    List<SupportWorkbenchEvent> incremental = service.events(supportId, cursor);
                    for (SupportWorkbenchEvent event : incremental) {
                        sendAuthorized(emitter, supportId, event);
                        cursor = event.cursor();
                    }
                }
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                emitter.complete();
            } catch (Exception exception) {
                emitter.completeWithError(exception);
            }
        });
    }

    private void sendAuthorized(SseEmitter emitter, String supportId, SupportWorkbenchEvent event)
            throws java.io.IOException {
        service.snapshot(supportId);
        emitter.send(SseEmitter.event()
                .id(event.cursor())
                .name(event.type())
                .data(event.publicData()));
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
