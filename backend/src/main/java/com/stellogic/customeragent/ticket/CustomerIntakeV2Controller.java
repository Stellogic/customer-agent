package com.stellogic.customeragent.ticket;

import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/customer/v2/intakes")
@ConditionalOnProperty(name = "baseline.migrate-only", havingValue = "false", matchIfMissing = true)
public final class CustomerIntakeV2Controller {
    static final String SCHEMA = "customer-intake-v1";
    private static final Set<String> MESSAGE_FIELDS = Set.of("schema", "message");
    private final CustomerIntakeService service;

    public CustomerIntakeV2Controller(CustomerIntakeService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<IntakeResponse> start(
            Authentication authentication,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody Map<String, Object> request) {
        MessageRequest message = parse(requestId, request);
        CustomerIntakeSnapshot snapshot =
                service.start(
                        new StartCustomerIntake(
                                authentication.getName(), message.requestId(), message.message()));
        return ResponseEntity.status(snapshot.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(IntakeResponse.from(snapshot));
    }

    @PostMapping("/{intakeId}/messages")
    ResponseEntity<IntakeResponse> reply(
            Authentication authentication,
            @PathVariable UUID intakeId,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody Map<String, Object> request) {
        MessageRequest message = parse(requestId, request);
        CustomerIntakeSnapshot snapshot =
                service.reply(
                        new ReplyCustomerIntake(
                                authentication.getName(),
                                intakeId,
                                message.requestId(),
                                message.message()));
        return ResponseEntity.status(snapshot.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(IntakeResponse.from(snapshot));
    }

    private static MessageRequest parse(String requestId, Map<String, Object> request) {
        if (!request.keySet().equals(MESSAGE_FIELDS)) {
            throw new InvalidCustomerRequestException("请求字段与受理契约不一致");
        }
        if (!SCHEMA.equals(request.get("schema"))) throw new IncompatibleCustomerSchemaException();
        return new MessageRequest(
                requireText(requestId, 200, "缺少稳定请求身份"),
                requireText(request.get("message"), 2000, "请输入需要帮助的内容"));
    }

    private static String requireText(Object value, int maximum, String message) {
        if (!(value instanceof String text) || text.isBlank() || text.length() > maximum) {
            throw new InvalidCustomerRequestException(message);
        }
        return text.trim();
    }

    private record MessageRequest(String requestId, String message) {}

    record IntakeResponse(
            String schema,
            UUID intakeId,
            String status,
            CandidateOrder candidateOrder,
            ProposedIssue issue,
            String assistantMessage,
            UUID ticketId,
            boolean confirmed,
            boolean replayed) {
        static IntakeResponse from(CustomerIntakeSnapshot snapshot) {
            CandidateOrder candidate =
                    snapshot.candidateOrderReference() == null
                            ? null
                            : new CandidateOrder(
                                    snapshot.candidateOrderReference(),
                                    snapshot.candidateOrderSummary());
            ProposedIssue issue =
                    snapshot.issueKind() == null
                            ? null
                            : new ProposedIssue(snapshot.issueKind(), snapshot.issueSummary());
            return new IntakeResponse(
                    SCHEMA,
                    snapshot.intakeId(),
                    snapshot.status(),
                    candidate,
                    issue,
                    snapshot.assistantMessage(),
                    snapshot.ticketId(),
                    snapshot.ticketId() != null,
                    snapshot.replayed());
        }
    }

    record CandidateOrder(String reference, String summary) {}

    record ProposedIssue(String kind, String summary) {}
}
