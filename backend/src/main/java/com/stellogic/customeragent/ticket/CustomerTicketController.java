package com.stellogic.customeragent.ticket;

import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/customer/tickets")
public final class CustomerTicketController {
    static final String CUSTOMER_HEADER = "X-Synthetic-Customer-Id";
    private static final Set<String> SYNTHETIC_CUSTOMERS = Set.of("customer-demo", "customer-other-demo");
    private final CustomerTicketService service;

    public CustomerTicketController(CustomerTicketService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<CreateTicketResponse> create(
            @RequestHeader(value = CUSTOMER_HEADER, required = false) String customerId,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody CreateTicketRequest request) {
        requireIdentity(customerId);
        requireText(requestId, "缺少稳定请求身份");
        requireText(request.orderReference(), "缺少订单编号");
        requireText(request.description(), "缺少问题描述");
        var result = service.create(new CreateCustomerTicket(
                customerId.trim(), requestId.trim(), request.orderReference().trim(), request.description().trim()));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(new CreateTicketResponse(result.ticketId(), result.replayed()));
    }

    @GetMapping("/{ticketId}")
    SnapshotResponse snapshot(
            @RequestHeader(value = CUSTOMER_HEADER, required = false) String customerId,
            @PathVariable UUID ticketId) {
        requireIdentity(customerId);
        return SnapshotResponse.from(service.snapshot(customerId.trim(), ticketId));
    }

    @GetMapping(value = "/{ticketId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter events(
            @RequestHeader(value = CUSTOMER_HEADER, required = false) String customerId,
            @RequestHeader(value = "Last-Event-ID", required = false) String cursor,
            @PathVariable UUID ticketId) {
        requireIdentity(customerId);
        String owner = customerId.trim();
        List<CustomerPublicEvent> events = service.events(owner, ticketId, cursor);
        SseEmitter emitter = new SseEmitter(60_000L);
        try {
            for (CustomerPublicEvent event : events) {
                send(emitter, event);
            }
            emitter.send(SseEmitter.event().comment("connected"));
        } catch (Exception exception) {
            emitter.completeWithError(exception);
            return emitter;
        }
        String nextCursor = events.isEmpty() ? cursor : events.getLast().cursor();
        startIncrementalStream(emitter, owner, ticketId, nextCursor);
        return emitter;
    }

    private void startIncrementalStream(SseEmitter emitter, String customerId, UUID ticketId, String initialCursor) {
        AtomicBoolean closed = new AtomicBoolean();
        emitter.onCompletion(() -> closed.set(true));
        emitter.onTimeout(() -> {
            closed.set(true);
            emitter.complete();
        });
        emitter.onError(error -> closed.set(true));
        Thread.ofVirtual().name("customer-ticket-events-" + ticketId).start(() -> {
            String cursor = initialCursor;
            try {
                while (!closed.get()) {
                    Thread.sleep(250);
                    List<CustomerPublicEvent> incremental = service.events(customerId, ticketId, cursor);
                    for (CustomerPublicEvent event : incremental) {
                        send(emitter, event);
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

    private static void send(SseEmitter emitter, CustomerPublicEvent event) throws java.io.IOException {
        emitter.send(SseEmitter.event()
                .id(event.cursor())
                .name(event.type())
                .data(event.jsonPayload()));
    }

    private static void requireIdentity(String customerId) {
        if (customerId == null || !SYNTHETIC_CUSTOMERS.contains(customerId.trim())) {
            throw new CustomerAuthenticationException();
        }
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank() || value.length() > 2000) {
            throw new InvalidCustomerRequestException(message);
        }
    }

    record CreateTicketRequest(String orderReference, String description) {}

    record CreateTicketResponse(UUID ticketId, boolean replayed) {}

    record SnapshotResponse(String view, String cursor, Ticket ticket, List<PublicMessage> messages) {
        static SnapshotResponse from(CustomerPublicSnapshot snapshot) {
            return new SnapshotResponse(
                    "CUSTOMER_PUBLIC",
                    snapshot.epoch() + ":" + snapshot.sequence(),
                    new Ticket(
                            snapshot.ticketId(),
                            snapshot.lifecycleState(),
                            snapshot.handlingMode(),
                            snapshot.createdAt(),
                            snapshot.firstRespondedAt()),
                    snapshot.messages());
        }
    }

    record Ticket(UUID id, String lifecycleState, String handlingMode, Instant createdAt, Instant firstRespondedAt) {}
}
