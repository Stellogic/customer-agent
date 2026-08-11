package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
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
                customerId.trim(), requestId.trim(), request.orderReference().trim(), request.description().trim(),
                "LOGISTICS_DELAY"));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(new CreateTicketResponse(result.ticketId(), true, result.replayed()));
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
        return AuthorizedSsePollingStream.open(
                "customer-ticket-events-" + ticketId, 250, 60_000L, cursor,
                new AuthorizedSsePollingStream.Source<CustomerPublicEvent>() {
                    @Override
                    public List<CustomerPublicEvent> events(String afterCursor) {
                        return service.events(owner, ticketId, afterCursor);
                    }

                    @Override
                    public void authorize() {
                        service.snapshot(owner, ticketId);
                    }

                    @Override
                    public String cursor(CustomerPublicEvent event) {
                        return event.cursor();
                    }

                    @Override
                    public SseEmitter.SseEventBuilder render(CustomerPublicEvent event) {
                        return SseEmitter.event().id(event.cursor()).name(event.type()).data(event.publicData());
                    }
                });
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

    record CreateTicketResponse(UUID ticketId, boolean accepted, boolean replayed) {}

    record SnapshotResponse(
            String view, String schema, String cursor, Ticket ticket, List<PublicMessage> messages,
            CurrentClarification clarification) {
        static SnapshotResponse from(CustomerPublicSnapshot snapshot) {
            return new SnapshotResponse(
                    "CUSTOMER_PUBLIC",
                    snapshot.epoch(),
                    snapshot.epoch() + ":" + snapshot.sequence(),
                    new Ticket(
                            snapshot.ticketId(),
                            snapshot.lifecycleState(),
                            snapshot.handlingMode(),
                            snapshot.agentGeneration(),
                            snapshot.createdAt(),
                            snapshot.firstRespondedAt()),
                    snapshot.messages(),
                    snapshot.clarification());
        }
    }

    record Ticket(
            UUID id, String lifecycleState, String handlingMode, long agentGeneration,
            Instant createdAt, Instant firstRespondedAt) {}
}
