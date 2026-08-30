package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
@RequestMapping("/api/customer/v2/tickets")
public final class CustomerTicketV2Controller {
    static final String SCHEMA = "public-conversation-v2";
    private static final String V1_SCHEMA = "customer-public-v1";
    private static final Set<String> CREATE_FIELDS =
            Set.of("schema", "orderReference", "description");
    private static final Set<String> MESSAGE_FIELDS = Set.of("schema", "message");
    private static final Set<String> EVENT_TYPES =
            Set.of(
                    "TICKET_ACCEPTED",
                    "PUBLIC_MESSAGE_APPENDED",
                    "TICKET_RESOLVED",
                    "CUSTOMER_CLARIFICATION_REQUESTED",
                    "TICKET_INVESTIGATION_RESUMED",
                    "TICKET_HANDED_OFF",
                    "TICKET_REOPENED",
                    "TICKET_CLOSED",
                    "CUSTOMER_MESSAGE_ACCEPTED",
                    "AGENT_PROCESSING_TERMINATED",
                    "AGENT_PROCESSING_STARTED",
                    "AGENT_REPLY_LOADING",
                    "PUBLIC_PROGRESS_UPDATED",
                    "AGENT_REPLY_STREAM_STARTED",
                    "AGENT_REPLY_CONTENT_DELTA",
                    "AGENT_REPLY_COMPLETED",
                    "AGENT_REPLY_ABORTED",
                    "AGENT_REPLY_FAILED",
                    "AUTO_RESOLUTION_CHANGED",
                    "COMPENSATION_REVIEW_PENDING",
                    "COMPENSATION_REVIEW_CLEARED");

    private final CustomerTicketService service;

    public CustomerTicketV2Controller(CustomerTicketService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<CreateResponse> create(
            Authentication authentication,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody Map<String, Object> request) {
        requireExactFields(request);
        String schema = text(request, "schema");
        if (!SCHEMA.equals(schema)) throw new IncompatibleCustomerSchemaException();
        requireText(requestId, "缺少稳定请求身份");
        String orderReference = text(request, "orderReference");
        String description = text(request, "description");
        var result =
                service.create(
                        new CreateCustomerTicket(
                                authentication.getName().trim(),
                                requestId.trim(),
                                orderReference,
                                description,
                                "LOGISTICS_DELAY"));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(new CreateResponse(SCHEMA, result.ticketId(), true, result.replayed()));
    }

    @PostMapping("/{ticketId}/messages")
    ResponseEntity<MessageResponse> appendMessage(
            Authentication authentication,
            @RequestHeader(value = "Idempotency-Key", required = false) String messageId,
            @PathVariable UUID ticketId,
            @RequestBody Map<String, Object> request) {
        if (!request.keySet().equals(MESSAGE_FIELDS)) {
            throw new InvalidCustomerRequestException("请求字段与 v2 消息契约不一致");
        }
        if (!SCHEMA.equals(text(request, "schema"))) {
            throw new IncompatibleCustomerSchemaException();
        }
        requireText(messageId, "缺少稳定消息身份");
        CustomerMessageResult result =
                service.appendMessage(
                        new AppendCustomerMessage(
                                authentication.getName().trim(),
                                ticketId,
                                messageId.trim(),
                                text(request, "message")));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.ACCEPTED)
                .body(new MessageResponse(SCHEMA, result.ticketId(), true, result.replayed()));
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
        String initialCursor = normalizeV2Cursor(cursor);
        return AuthorizedSsePollingStream.open(
                "customer-ticket-v2-events-" + ticketId,
                250,
                AuthorizedSsePollingStream.MAX_AUTHORIZATION_STALENESS_MILLIS,
                initialCursor,
                AuthorizedSsePollingStream.requireCurrentHttpSession(
                        request,
                        owner,
                        new AuthorizedSsePollingStream.Source<V2Event>() {
                            @Override
                            public List<V2Event> events(String afterCursor) {
                                long sequence = parseV2Sequence(afterCursor);
                                return service
                                        .events(owner, ticketId, V1_SCHEMA + ":" + sequence)
                                        .stream()
                                        .map(V2Event::from)
                                        .toList();
                            }

                            @Override
                            public void authorize() {
                                service.snapshot(owner, ticketId);
                            }

                            @Override
                            public String cursor(V2Event event) {
                                return event.cursor();
                            }

                            @Override
                            public SseEmitter.SseEventBuilder render(V2Event event) {
                                return SseEmitter.event()
                                        .id(event.cursor())
                                        .name(event.type())
                                        .data(event.publicData());
                            }
                        }));
    }

    private static void requireExactFields(Map<String, Object> request) {
        if (!request.keySet().equals(CREATE_FIELDS)) {
            throw new InvalidCustomerRequestException("请求字段与 v2 契约不一致");
        }
    }

    private static String text(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof String text)) {
            throw new InvalidCustomerRequestException("字段类型无效: " + field);
        }
        requireText(text, "字段内容无效: " + field);
        return text.trim();
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank() || value.length() > 2000) {
            throw new InvalidCustomerRequestException(message);
        }
    }

    private static String normalizeV2Cursor(String cursor) {
        return SCHEMA + ":" + parseV2Sequence(cursor);
    }

    private static long parseV2Sequence(String cursor) {
        if (cursor == null || cursor.isBlank()) return 0;
        int separator = cursor.lastIndexOf(':');
        if (separator < 1 || !SCHEMA.equals(cursor.substring(0, separator))) {
            throw new ProjectionCursorException();
        }
        try {
            long sequence = Long.parseLong(cursor.substring(separator + 1));
            if (sequence < 0) throw new ProjectionCursorException();
            return sequence;
        } catch (NumberFormatException exception) {
            throw new ProjectionCursorException();
        }
    }

    record CreateResponse(String schema, UUID ticketId, boolean accepted, boolean replayed) {}

    record MessageResponse(String schema, UUID ticketId, boolean accepted, boolean replayed) {}

    record SnapshotResponse(
            String view,
            String schema,
            String cursor,
            Ticket ticket,
            List<PublicMessage> messages,
            CurrentClarification clarification,
            CurrentReplyStream replyStream,
            CurrentAutoResolution autoResolution,
            PendingCompensationProjection pendingCompensation) {
        static SnapshotResponse from(CustomerPublicSnapshot snapshot) {
            return new SnapshotResponse(
                    "PUBLIC_CONVERSATION",
                    SCHEMA,
                    SCHEMA + ":" + snapshot.sequence(),
                    new Ticket(
                            snapshot.ticketId(),
                            snapshot.lifecycleState(),
                            snapshot.handlingMode(),
                            snapshot.agentGeneration()),
                    snapshot.messages(),
                    snapshot.clarification(),
                    snapshot.replyStream(),
                    snapshot.autoResolution(),
                    snapshot.pendingCompensation());
        }
    }

    record Ticket(UUID id, String lifecycleState, String handlingMode, long agentGeneration) {}

    record V2Event(long sequence, long generation, String type, String jsonPayload) {
        static V2Event from(CustomerPublicEvent event) {
            if (!V1_SCHEMA.equals(event.epoch()) || !EVENT_TYPES.contains(event.type())) {
                throw new ProjectionCursorException();
            }
            return new V2Event(
                    event.sequence(), event.agentGeneration(), event.type(), event.jsonPayload());
        }

        String cursor() {
            return SCHEMA + ":" + sequence;
        }

        String publicData() {
            return "{\"view\":\"PUBLIC_CONVERSATION\",\"schema\":\""
                    + SCHEMA
                    + "\",\"generation\":"
                    + generation
                    + ",\"payload\":"
                    + jsonPayload
                    + "}";
        }
    }
}
