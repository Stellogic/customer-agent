package com.stellogic.customeragent.ticket;

import java.math.BigInteger;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
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
    static final String SCHEMA = "customer-intake-v4";
    private static final Set<String> START_FIELDS = Set.of("schema", "message");
    private static final Set<String> REPLY_FIELDS = Set.of("schema", "message", "expectedVersion");
    private static final Set<String> DUPLICATE_FIELDS =
            Set.of("schema", "existingTicketId", "action", "expectedVersion");
    private static final String RECOVERY_SCHEMA = "customer-intake-recovery-v1";
    private static final Set<String> RESTORE_FIELDS = Set.of("schema", "expectedVersion");
    private final CustomerIntakeService service;

    public CustomerIntakeV2Controller(CustomerIntakeService service) {
        this.service = service;
    }

    @PostMapping
    ResponseEntity<IntakeResponse> start(
            Authentication authentication,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody Map<String, Object> request) {
        MessageRequest message = parseStart(requestId, request);
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
        VersionedMessageRequest message = parseReply(requestId, request);
        CustomerIntakeSnapshot snapshot =
                service.reply(
                        new ReplyCustomerIntake(
                                authentication.getName(),
                                intakeId,
                                message.requestId(),
                                message.message(),
                                message.expectedVersion()));
        return ResponseEntity.status(snapshot.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(IntakeResponse.from(snapshot));
    }

    @GetMapping("/{intakeId}")
    IntakeResponse snapshot(Authentication authentication, @PathVariable UUID intakeId) {
        return IntakeResponse.from(service.snapshot(authentication.getName(), intakeId));
    }

    @GetMapping("/recovery")
    RecoveryIndexResponse recoveryIndex(Authentication authentication) {
        return RecoveryIndexResponse.from(service.recoveryIndex(authentication.getName()));
    }

    @GetMapping("/{intakeId}/recovery")
    RecoverableIntakeResponse recoverableSnapshot(
            Authentication authentication, @PathVariable UUID intakeId) {
        return RecoverableIntakeResponse.from(
                service.recoverableSnapshot(authentication.getName(), intakeId));
    }

    @PostMapping("/{intakeId}/restore")
    ResponseEntity<RecoverableIntakeResponse> restore(
            Authentication authentication,
            @PathVariable UUID intakeId,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody Map<String, Object> request) {
        if (!request.keySet().equals(RESTORE_FIELDS)
                || !RECOVERY_SCHEMA.equals(request.get("schema"))) {
            throw new InvalidCustomerRequestException("归档受理恢复字段与版本无效");
        }
        long expectedVersion = requirePositiveLong(request.get("expectedVersion"));
        RecoverableCustomerIntake restored =
                service.restore(
                        new RestoreCustomerIntake(
                                authentication.getName(),
                                intakeId,
                                requireText(requestId, 200, "缺少稳定请求身份"),
                                expectedVersion));
        return ResponseEntity.status(
                        restored.intake().replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(RecoverableIntakeResponse.from(restored));
    }

    @PostMapping("/{intakeId}/duplicate-resolution")
    ResponseEntity<IntakeResponse> resolveDuplicate(
            Authentication authentication,
            @PathVariable UUID intakeId,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @RequestBody Map<String, Object> request) {
        if (!request.keySet().equals(DUPLICATE_FIELDS) || !SCHEMA.equals(request.get("schema"))) {
            throw new InvalidCustomerRequestException("重复问题确认字段与受理契约不一致");
        }
        String action = requireText(request.get("action"), 40, "请选择如何处理疑似重复问题");
        if (!Set.of("CONTINUE_EXISTING", "CREATE_NEW").contains(action)) {
            throw new InvalidCustomerRequestException("重复问题处理方式无效");
        }
        UUID existingTicketId;
        try {
            existingTicketId =
                    UUID.fromString(requireText(request.get("existingTicketId"), 36, "缺少既有工单"));
        } catch (IllegalArgumentException exception) {
            throw new InvalidCustomerRequestException("既有工单编号无效");
        }
        CustomerIntakeSnapshot snapshot =
                service.resolveDuplicate(
                        new ResolveDuplicateIntake(
                                authentication.getName(),
                                intakeId,
                                requireText(requestId, 200, "缺少稳定请求身份"),
                                existingTicketId,
                                action,
                                requirePositiveLong(request.get("expectedVersion"))));
        return ResponseEntity.status(snapshot.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(IntakeResponse.from(snapshot));
    }

    private static MessageRequest parseStart(String requestId, Map<String, Object> request) {
        if (!request.keySet().equals(START_FIELDS)) {
            throw new InvalidCustomerRequestException("请求字段与受理契约不一致");
        }
        if (!SCHEMA.equals(request.get("schema"))) {
            throw new IncompatibleCustomerSchemaException();
        }
        return new MessageRequest(
                requireText(requestId, 200, "缺少稳定请求身份"),
                requireText(request.get("message"), 2000, "请输入需要帮助的内容"));
    }

    private static VersionedMessageRequest parseReply(
            String requestId, Map<String, Object> request) {
        if (!request.keySet().equals(REPLY_FIELDS)) {
            throw new InvalidCustomerRequestException("请求字段与受理契约不一致");
        }
        if (!SCHEMA.equals(request.get("schema"))) {
            throw new IncompatibleCustomerSchemaException();
        }
        return new VersionedMessageRequest(
                requireText(requestId, 200, "缺少稳定请求身份"),
                requireText(request.get("message"), 2000, "请输入需要帮助的内容"),
                requirePositiveLong(request.get("expectedVersion")));
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

    private record MessageRequest(String requestId, String message) {}

    private record VersionedMessageRequest(
            String requestId, String message, long expectedVersion) {}

    record IntakeResponse(
            String schema,
            UUID intakeId,
            String status,
            CandidateOrder candidateOrder,
            java.util.List<ProposedIssue> issues,
            String assistantMessage,
            java.util.List<UUID> ticketIds,
            UUID sharedIntakeRecordId,
            java.util.List<DuplicateMatch> duplicateMatches,
            java.util.List<UUID> routedTicketIds,
            int remainingOrderCount,
            int completedOrderCount,
            int expectedTicketCount,
            boolean confirmed,
            long version,
            boolean replayed) {
        static IntakeResponse from(CustomerIntakeSnapshot snapshot) {
            CandidateOrder candidate =
                    snapshot.candidateOrderReference() == null
                            ? null
                            : new CandidateOrder(
                                    snapshot.candidateOrderReference(),
                                    snapshot.candidateOrderSummary());
            java.util.List<ProposedIssue> issues =
                    snapshot.issues().stream()
                            .map(value -> new ProposedIssue(value.kind(), value.summary()))
                            .toList();
            return new IntakeResponse(
                    SCHEMA,
                    snapshot.intakeId(),
                    snapshot.status(),
                    candidate,
                    issues,
                    snapshot.assistantMessage(),
                    snapshot.ticketIds(),
                    snapshot.sharedIntakeRecordId(),
                    snapshot.duplicateMatches().stream().map(DuplicateMatch::from).toList(),
                    snapshot.routedTicketIds(),
                    snapshot.remainingOrderCount(),
                    snapshot.completedOrderCount(),
                    snapshot.issues().size(),
                    "CONFIRMED".equals(snapshot.status()),
                    snapshot.version(),
                    snapshot.replayed());
        }
    }

    record CandidateOrder(String reference, String summary) {}

    record ProposedIssue(String kind, String summary) {}

    record DuplicateMatch(
            UUID ticketId, String issueKind, String issueSummary, String lifecycleState) {
        static DuplicateMatch from(DuplicateIntakeMatch match) {
            return new DuplicateMatch(
                    match.ticketId(),
                    match.issueKind(),
                    match.issueSummary(),
                    match.lifecycleState());
        }
    }

    record RecoveryIndexResponse(
            String schema,
            java.util.List<RecoverableIntakeResponse> active,
            java.util.List<RecoverableIntakeResponse> archived) {
        static RecoveryIndexResponse from(CustomerIntakeRecoveryIndex index) {
            return new RecoveryIndexResponse(
                    RECOVERY_SCHEMA,
                    index.active().stream().map(RecoverableIntakeResponse::from).toList(),
                    index.archived().stream().map(RecoverableIntakeResponse::from).toList());
        }
    }

    record RecoverableIntakeResponse(
            IntakeResponse intake,
            long version,
            String retentionState,
            java.time.Instant expiresAt,
            java.time.Instant archivedAt,
            boolean factsChanged,
            java.util.List<ConversationMessage> messages) {
        static RecoverableIntakeResponse from(RecoverableCustomerIntake value) {
            return new RecoverableIntakeResponse(
                    IntakeResponse.from(value.intake()),
                    value.version(),
                    value.retentionState(),
                    value.expiresAt(),
                    value.archivedAt(),
                    value.factsChanged(),
                    value.messages().stream().map(ConversationMessage::from).toList());
        }
    }

    record ConversationMessage(String author, String body, java.time.Instant sentAt) {
        static ConversationMessage from(IntakeConversationMessage message) {
            return new ConversationMessage(message.author(), message.body(), message.sentAt());
        }
    }
}
