package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
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
@RequestMapping("/api/customer/tickets")
public final class CustomerTicketController {
    private final CustomerTicketService service;

    public CustomerTicketController(CustomerTicketService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<CreateTicketResponse> create(
            Authentication authentication,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody CreateTicketRequest request) {
        String customerId = authentication.getName();
        requireText(requestId, "缺少稳定请求身份");
        requireText(request.orderReference(), "缺少订单编号");
        requireText(request.description(), "缺少问题描述");
        var result =
                service.create(
                        new CreateCustomerTicket(
                                customerId.trim(),
                                requestId.trim(),
                                request.orderReference().trim(),
                                request.description().trim(),
                                "LOGISTICS_DELAY"));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(new CreateTicketResponse(result.ticketId(), true, result.replayed()));
    }

    @GetMapping("/{ticketId}")
    SnapshotResponse snapshot(Authentication authentication, @PathVariable UUID ticketId) {
        return SnapshotResponse.from(service.snapshot(authentication.getName(), ticketId));
    }

    @GetMapping(value = "/{ticketId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    SseEmitter events(
            Authentication authentication,
            HttpServletRequest request,
            @RequestHeader(value = "Last-Event-ID", required = false) String cursor,
            @PathVariable UUID ticketId) {
        String owner = authentication.getName();
        return AuthorizedSsePollingStream.open(
                "customer-ticket-events-" + ticketId,
                250,
                AuthorizedSsePollingStream.MAX_AUTHORIZATION_STALENESS_MILLIS,
                cursor,
                AuthorizedSsePollingStream.requireCurrentHttpSession(
                        request,
                        owner,
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
                                return SseEmitter.event()
                                        .id(event.cursor())
                                        .name(event.type())
                                        .data(event.publicData());
                            }
                        }));
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank() || value.length() > 2000) {
            throw new InvalidCustomerRequestException(message);
        }
    }

    record CreateTicketRequest(String orderReference, String description) {}

    record CreateTicketResponse(UUID ticketId, boolean accepted, boolean replayed) {}

    record SnapshotResponse(
            String view,
            String schema,
            String cursor,
            Ticket ticket,
            List<PublicMessage> messages,
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
            UUID id,
            String lifecycleState,
            String handlingMode,
            long agentGeneration,
            Instant createdAt,
            Instant firstRespondedAt) {}
}
