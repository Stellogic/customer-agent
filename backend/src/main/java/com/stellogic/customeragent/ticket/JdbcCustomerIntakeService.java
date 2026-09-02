package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.closure.ClosureService;
import com.stellogic.customeragent.reliability.StableParameterDigest;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@ConditionalOnProperty(name = "baseline.migrate-only", havingValue = "false", matchIfMissing = true)
class JdbcCustomerIntakeService implements CustomerIntakeService {
    private final JdbcTemplate jdbc;
    private final IntakeUnderstandingGateway agent;
    private final CustomerTicketService tickets;
    private final ClosureService closure;
    private final IntakeAssistanceService assistance;
    private final Clock clock;

    JdbcCustomerIntakeService(
            JdbcTemplate jdbc,
            IntakeUnderstandingGateway agent,
            CustomerTicketService tickets,
            ClosureService closure,
            IntakeAssistanceService assistance,
            Clock clock) {
        this.jdbc = jdbc;
        this.agent = agent;
        this.tickets = tickets;
        this.closure = closure;
        this.assistance = assistance;
        this.clock = clock;
    }

    @Override
    @Transactional
    public CustomerIntakeSnapshot start(StartCustomerIntake command) {
        String digest = StableParameterDigest.sha256(command.message());
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                resultSet -> null,
                command.customerId() + "\n" + command.requestId());
        List<IntakeRow> existing =
                jdbc.query(
                        "select "
                                + intakeColumns()
                                + " from customer_intake "
                                + "where customer_id = ? and start_request_key = ? for update",
                        (rs, row) -> map(rs),
                        command.customerId(),
                        command.requestId());
        if (!existing.isEmpty()) {
            IntakeRow row = existing.getFirst();
            if (!row.startDigest().equals(digest)) {
                throw new IntakeRequestIdentityConflictException(snapshot(enrich(row), true));
            }
            return snapshot(enrich(row), true);
        }

        if (CustomerIntakeSafetyPolicy.isHumanAssistanceRequest(command.message())) {
            return createAssistedIntake(command, "CUSTOMER_REQUESTED");
        }
        List<CustomerVisibleOrderSummary> orders = visibleOrders(command.customerId());
        IntakeUnderstanding understanding;
        try {
            understanding =
                    agent.understand(
                            new IntakeUnderstandingRequest(
                                    command.message(),
                                    orders,
                                    null,
                                    null,
                                    List.of(),
                                    List.of(),
                                    List.of()));
            requireUnderstanding(understanding, orders);
        } catch (IntakeAgentUnavailableException exception) {
            return createAssistedIntake(command, "AGENT_UNAVAILABLE");
        }
        String assistantMessage = CustomerIntakeSafetyPolicy.assistantMessage(understanding);
        UUID intakeId = UUID.randomUUID();
        CustomerVisibleOrderSummary candidate = candidate(understanding, orders);
        Instant now = clock.instant();
        jdbc.update(
                "insert into customer_intake "
                        + "(id, customer_id, start_request_key, start_digest, original_message, status, "
                        + "candidate_order_reference, candidate_order_version, candidate_order_summary, issue_kind, "
                        + "issue_summary, assistant_message, created_at, updated_at, expires_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                intakeId,
                command.customerId(),
                command.requestId(),
                digest,
                command.message(),
                understanding.status(),
                understanding.candidateOrderReference(),
                candidate == null ? null : candidate.version(),
                candidate == null ? null : candidate.summary(),
                firstKind(understanding.issues()),
                firstSummary(understanding.issues()),
                assistantMessage,
                timestamp(now),
                timestamp(now),
                timestamp(now.plus(Duration.ofDays(7))));
        replaceIssues(intakeId, understanding.issues());
        replacePendingIssueKinds(intakeId, understanding.pendingIssueKinds());
        replacePendingOrders(intakeId, understanding.remainingOrderReferences(), orders);
        syncDuplicateMatches(
                intakeId,
                command.customerId(),
                understanding.candidateOrderReference(),
                understanding.issues());
        appendTranscript(intakeId, "CUSTOMER", command.message(), now);
        appendTranscript(intakeId, "AGENT", assistantMessage, now);
        return snapshot(load(command.customerId(), intakeId), false);
    }

    @Override
    @Transactional(noRollbackFor = IntakeArchivedException.class)
    public CustomerIntakeSnapshot reply(ReplyCustomerIntake command) {
        IntakeRow current = loadForUpdate(command.customerId(), command.intakeId());
        String digest = StableParameterDigest.sha256(command.message());
        List<MessageIdentity> prior =
                jdbc.query(
                        "select request_digest from customer_intake_message "
                                + "where intake_id = ? and request_key = ?",
                        (rs, row) -> new MessageIdentity(rs.getString(1)),
                        command.intakeId(),
                        command.requestId());
        if (!prior.isEmpty()) {
            if (!prior.getFirst().digest().equals(digest)) {
                throw new IntakeRequestIdentityConflictException(snapshot(current, true));
            }
            return snapshot(current, true);
        }
        current = requireActive(current);
        requireVersion(current, command.expectedVersion());
        Instant now = clock.instant();
        jdbc.update(
                "insert into customer_intake_message "
                        + "(intake_id, request_key, request_digest, customer_message, created_at) "
                        + "values (?, ?, ?, ?, ?)",
                command.intakeId(),
                command.requestId(),
                digest,
                command.message(),
                timestamp(now));
        appendTranscript(command.intakeId(), "CUSTOMER", command.message(), now);
        if ("CONFIRMED".equals(current.status())) return snapshot(current, true);

        if (CustomerIntakeSafetyPolicy.isHumanAssistanceRequest(command.message())) {
            assistance.createForIntake(command.intakeId(), "CUSTOMER_REQUESTED");
        }
        if (assistance.hasOpenRequest(command.intakeId())) {
            if (CustomerIntakeSafetyPolicy.isExplicitConfirmation(command.message())
                    && "READY_TO_CONFIRM".equals(current.status())
                    && assistance.awaitingCustomerConfirmation(command.intakeId())) {
                CustomerIntakeSnapshot confirmed =
                        confirm(
                                command,
                                current,
                                "已确认，" + current.issues().size() + " 张客服工单已原子创建并开始独立处理。");
                assistance.completeForIntake(command.intakeId());
                return confirmed;
            }
            return retainHumanAssistance(command.customerId(), command.intakeId(), now);
        }

        List<CustomerVisibleOrderSummary> orders = visibleOrders(command.customerId());
        IntakeUnderstanding understanding;
        try {
            understanding =
                    agent.understand(
                            new IntakeUnderstandingRequest(
                                    command.message(),
                                    orders,
                                    current.orderReference(),
                                    firstSummary(current.issues()),
                                    current.issues(),
                                    current.pendingIssueKinds(),
                                    current.pendingOrders().stream()
                                            .map(PendingOrder::reference)
                                            .toList()));
        } catch (IntakeAgentUnavailableException exception) {
            assistance.createForIntake(command.intakeId(), "AGENT_UNAVAILABLE");
            return retainHumanAssistance(command.customerId(), command.intakeId(), now);
        }
        try {
            if ("CONFIRM".equals(understanding.intent())) {
                if (!CustomerIntakeSafetyPolicy.isExplicitConfirmation(command.message())) {
                    throw new IntakeAgentUnavailableException();
                }
                return confirm(
                        command, current, "已确认，" + current.issues().size() + " 张客服工单已原子创建并开始独立处理。");
            }
            requireUnderstanding(understanding, orders);
        } catch (IntakeAgentUnavailableException exception) {
            assistance.createForIntake(command.intakeId(), "AGENT_UNAVAILABLE");
            return retainHumanAssistance(command.customerId(), command.intakeId(), now);
        }
        String assistantMessage = CustomerIntakeSafetyPolicy.assistantMessage(understanding);
        CustomerVisibleOrderSummary candidate = candidate(understanding, orders);
        jdbc.update(
                "update customer_intake set status = ?, candidate_order_reference = ?, "
                        + "candidate_order_version = ?, candidate_order_summary = ?, issue_kind = ?, "
                        + "issue_summary = ?, assistant_message = ?, updated_at = ?, expires_at = ?, "
                        + "version = version + 1 where id = ?",
                understanding.status(),
                understanding.candidateOrderReference(),
                candidate == null ? null : candidate.version(),
                candidate == null ? null : candidate.summary(),
                firstKind(understanding.issues()),
                firstSummary(understanding.issues()),
                assistantMessage,
                timestamp(now),
                timestamp(now.plus(Duration.ofDays(7))),
                command.intakeId());
        replaceIssues(command.intakeId(), understanding.issues());
        replacePendingIssueKinds(command.intakeId(), understanding.pendingIssueKinds());
        replacePendingOrders(command.intakeId(), understanding.remainingOrderReferences(), orders);
        syncDuplicateMatches(
                command.intakeId(),
                command.customerId(),
                understanding.candidateOrderReference(),
                understanding.issues());
        appendTranscript(command.intakeId(), "AGENT", assistantMessage, now);
        return snapshot(load(command.customerId(), command.intakeId()), false);
    }

    @Override
    @Transactional(noRollbackFor = IntakeArchivedException.class)
    public CustomerIntakeSnapshot snapshot(String customerId, UUID intakeId) {
        return snapshot(requireActive(loadForUpdate(customerId, intakeId)), false);
    }

    @Override
    @Transactional(noRollbackFor = IntakeArchivedException.class)
    public CustomerIntakeSnapshot resolveDuplicate(ResolveDuplicateIntake command) {
        IntakeRow current = loadForUpdate(command.customerId(), command.intakeId());
        String digest =
                StableParameterDigest.sha256(
                        command.existingTicketId().toString(), command.action());
        List<MessageIdentity> prior =
                jdbc.query(
                        "select request_digest from customer_intake_duplicate_resolution_request "
                                + "where intake_id = ? and request_key = ?",
                        (rs, row) -> new MessageIdentity(rs.getString(1)),
                        command.intakeId(),
                        command.requestId());
        if (!prior.isEmpty()) {
            if (!prior.getFirst().digest().equals(digest)) {
                throw new IntakeRequestIdentityConflictException(snapshot(current, true));
            }
            return snapshot(current, true);
        }
        current = requireActive(current);
        requireVersion(current, command.expectedVersion());
        DuplicateIntakeMatch selected =
                current.duplicateMatches().stream()
                        .filter(match -> match.ticketId().equals(command.existingTicketId()))
                        .findFirst()
                        .orElseThrow(IntakeNotReadyException::new);
        jdbc.update(
                "insert into customer_intake_duplicate_resolution_request "
                        + "(intake_id, request_key, request_digest, existing_ticket_id, action, created_at) "
                        + "values (?, ?, ?, ?, ?, current_timestamp)",
                command.intakeId(),
                command.requestId(),
                digest,
                command.existingTicketId(),
                command.action());
        appendTranscript(
                command.intakeId(),
                "CUSTOMER",
                "CONTINUE_EXISTING".equals(command.action()) ? "继续既有工单" : "作为新问题继续创建",
                clock.instant());
        jdbc.update(
                "update customer_intake_duplicate_match set resolution = ?, resolved_at = current_timestamp "
                        + "where intake_id = ? and issue_kind = ? and resolution is null",
                command.action(),
                command.intakeId(),
                selected.issueKind());
        if ("CONTINUE_EXISTING".equals(command.action())) {
            UUID routedTicketId = selected.ticketId();
            if ("RESOLVED".equals(selected.lifecycleState())
                    || "CLOSED".equals(selected.lifecycleState())) {
                routedTicketId =
                        closure.continueFromConfirmedIntake(
                                command.customerId(),
                                selected.ticketId(),
                                "intake:" + command.intakeId() + ":" + selected.issueKind(),
                                current.orderReference(),
                                selected.issueKind(),
                                current.originalMessage());
            }
            jdbc.update(
                    "insert into customer_intake_routed_ticket "
                            + "(intake_id, order_reference, issue_kind, ticket_id, routed_at) "
                            + "values (?, ?, ?, ?, current_timestamp) on conflict do nothing",
                    command.intakeId(),
                    current.orderReference(),
                    selected.issueKind(),
                    routedTicketId);
            jdbc.update(
                    "delete from customer_intake_issue where intake_id = ? and issue_kind = ?",
                    command.intakeId(),
                    selected.issueKind());
        }
        Instant activityTime = clock.instant();
        jdbc.update(
                "update customer_intake set updated_at = ?, expires_at = ?, version = version + 1 "
                        + "where id = ?",
                timestamp(activityTime),
                timestamp(activityTime.plus(Duration.ofDays(7))),
                command.intakeId());
        current = loadForUpdate(command.customerId(), command.intakeId());
        if (!current.duplicateMatches().isEmpty()) return snapshot(current, false);
        if (current.issues().isEmpty()) {
            return completeCurrentOrder(
                    command.customerId(), command.intakeId(), "已按你的确认继续既有工单，没有创建重复工单。");
        }
        Instant readyTime = clock.instant();
        jdbc.update(
                "update customer_intake set status = 'READY_TO_CONFIRM', issue_kind = ?, issue_summary = ?, "
                        + "assistant_message = ?, updated_at = ?, expires_at = ?, version = version + 1 where id = ?",
                firstKind(current.issues()),
                firstSummary(current.issues()),
                "重复问题已按你的选择处理；请确认当前订单仍需创建的新问题。",
                timestamp(readyTime),
                timestamp(readyTime.plus(Duration.ofDays(7))),
                command.intakeId());
        appendTranscript(command.intakeId(), "AGENT", "重复问题已按你的选择处理；请确认当前订单仍需创建的新问题。", readyTime);
        return snapshot(load(command.customerId(), command.intakeId()), false);
    }

    @Override
    @Transactional
    public CustomerIntakeRecoveryIndex recoveryIndex(String customerId) {
        Instant now = clock.instant();
        jdbc.update(
                "update customer_intake set retention_state = 'ARCHIVED', archived_at = ?, "
                        + "updated_at = ?, version = version + 1 "
                        + "where customer_id = ? and retention_state = 'ACTIVE' "
                        + "and status <> 'CONFIRMED' and expires_at <= ?",
                timestamp(now),
                timestamp(now),
                customerId,
                timestamp(now));
        List<IntakeRow> rows =
                jdbc
                        .query(
                                "select "
                                        + intakeColumns()
                                        + " from customer_intake where customer_id = ? "
                                        + "and retention_state in ('ACTIVE', 'ARCHIVED') "
                                        + "order by updated_at desc, id",
                                (rs, row) -> map(rs),
                                customerId)
                        .stream()
                        .map(this::enrich)
                        .toList();
        List<RecoverableCustomerIntake> active =
                rows.stream()
                        .filter(row -> "ACTIVE".equals(row.retentionState()))
                        .map(row -> recoverable(row, false))
                        .toList();
        List<RecoverableCustomerIntake> archived =
                rows.stream()
                        .filter(row -> "ARCHIVED".equals(row.retentionState()))
                        .map(row -> recoverable(row, false))
                        .toList();
        return new CustomerIntakeRecoveryIndex(active, archived);
    }

    @Override
    @Transactional(noRollbackFor = IntakeArchivedException.class)
    public RecoverableCustomerIntake recoverableSnapshot(String customerId, UUID intakeId) {
        IntakeRow current = archiveIfExpired(loadForUpdate(customerId, intakeId));
        return recoverable(current, false);
    }

    @Override
    @Transactional(noRollbackFor = IntakeVersionConflictException.class)
    public RecoverableCustomerIntake restore(RestoreCustomerIntake command) {
        IntakeRow current =
                archiveIfExpired(loadForUpdate(command.customerId(), command.intakeId()));
        String digest = StableParameterDigest.sha256(Long.toString(command.expectedVersion()));
        List<RestoreIdentity> prior =
                jdbc.query(
                        "select request_digest from customer_intake_restore_request "
                                + "where intake_id = ? and request_key = ?",
                        (rs, row) -> new RestoreIdentity(rs.getString(1)),
                        command.intakeId(),
                        command.requestId());
        if (!prior.isEmpty()) {
            if (!prior.getFirst().digest().equals(digest)) {
                throw new RequestIdentityConflictException();
            }
            return recoverable(load(command.customerId(), command.intakeId()), true);
        }
        if (!"ARCHIVED".equals(current.retentionState())
                || current.version() != command.expectedVersion()) {
            throw new IntakeVersionConflictException();
        }

        List<CustomerVisibleOrderSummary> orders = visibleOrders(command.customerId());
        boolean candidateOwnershipLost =
                current.orderReference() != null
                        && orders.stream()
                                .noneMatch(
                                        order ->
                                                order.reference().equals(current.orderReference()));
        List<String> visibleRemainingOrders =
                current.pendingOrders().stream()
                        .map(PendingOrder::reference)
                        .filter(
                                reference ->
                                        orders.stream()
                                                .anyMatch(
                                                        order ->
                                                                order.reference()
                                                                        .equals(reference)))
                        .toList();
        IntakeUnderstanding understanding =
                candidateOwnershipLost
                        ? new IntakeUnderstanding(
                                "UNDERSTANDING",
                                "NEEDS_CLARIFICATION",
                                null,
                                List.of(),
                                List.of(),
                                List.of(),
                                "原订单已不再可见，请补充订单线索。")
                        : agent.understand(
                                new IntakeUnderstandingRequest(
                                        latestCustomerMessage(
                                                current.id(), current.originalMessage()),
                                        orders,
                                        current.orderReference(),
                                        firstSummary(current.issues()),
                                        current.issues(),
                                        current.pendingIssueKinds(),
                                        visibleRemainingOrders));
        requireUnderstanding(understanding, orders);
        CustomerVisibleOrderSummary candidate = candidate(understanding, orders);
        boolean factsChanged = factsChanged(current, orders, candidate);
        String assistantMessage =
                candidate == null
                        ? "订单事实已变化；原订单已不再可见，请补充订单线索后重新确认。"
                        : factsChanged
                                ? "订单事实已变化；已重新核对候选，请重新确认后再创建工单。"
                                : "已重新核对当前订单事实，请再次确认后再创建工单。";
        Instant now = clock.instant();
        jdbc.update(
                "update customer_intake set retention_state = 'ACTIVE', archived_at = null, "
                        + "restored_at = ?, expires_at = ?, facts_changed = ?, version = version + 1, "
                        + "status = ?, candidate_order_reference = ?, candidate_order_version = ?, "
                        + "candidate_order_summary = ?, issue_kind = ?, issue_summary = ?, "
                        + "assistant_message = ?, updated_at = ? where id = ? and version = ?",
                timestamp(now),
                timestamp(now.plus(Duration.ofDays(7))),
                factsChanged,
                understanding.status(),
                understanding.candidateOrderReference(),
                candidate == null ? null : candidate.version(),
                candidate == null ? null : candidate.summary(),
                firstKind(understanding.issues()),
                firstSummary(understanding.issues()),
                assistantMessage,
                timestamp(now),
                command.intakeId(),
                command.expectedVersion());
        replaceIssues(command.intakeId(), understanding.issues());
        replacePendingIssueKinds(command.intakeId(), understanding.pendingIssueKinds());
        replacePendingOrders(command.intakeId(), understanding.remainingOrderReferences(), orders);
        syncDuplicateMatches(
                command.intakeId(),
                command.customerId(),
                understanding.candidateOrderReference(),
                understanding.issues());
        appendTranscript(command.intakeId(), "AGENT", assistantMessage, now);
        jdbc.update(
                "insert into customer_intake_restore_request "
                        + "(intake_id, request_key, request_digest, resulting_version, created_at) "
                        + "values (?, ?, ?, ?, ?)",
                command.intakeId(),
                command.requestId(),
                digest,
                command.expectedVersion() + 1,
                timestamp(now));
        return recoverable(load(command.customerId(), command.intakeId()), false);
    }

    private CustomerIntakeSnapshot createAssistedIntake(
            StartCustomerIntake command, String reasonCode) {
        UUID intakeId = UUID.randomUUID();
        Instant now = clock.instant();
        String assistantMessage = "已建立受理协助请求；客服只能协助确认订单与拟建问题，仍需由你确认后才会创建正式工单。";
        jdbc.update(
                "insert into customer_intake "
                        + "(id, customer_id, start_request_key, start_digest, original_message, status, "
                        + "assistant_message, created_at, updated_at, expires_at) "
                        + "values (?, ?, ?, ?, ?, 'NEEDS_CLARIFICATION', ?, ?, ?, ?)",
                intakeId,
                command.customerId(),
                command.requestId(),
                StableParameterDigest.sha256(command.message()),
                command.message(),
                assistantMessage,
                timestamp(now),
                timestamp(now),
                timestamp(now.plus(Duration.ofDays(7))));
        appendTranscript(intakeId, "CUSTOMER", command.message(), now);
        appendTranscript(intakeId, "AGENT", assistantMessage, now);
        assistance.createForIntake(intakeId, reasonCode);
        return snapshot(load(command.customerId(), intakeId), false);
    }

    private CustomerIntakeSnapshot retainHumanAssistance(
            String customerId, UUID intakeId, Instant now) {
        String assistantMessage = "受理协助仍由客服负责；客服可以修正订单候选与拟建问题，但不会代替你确认或提前创建工单。";
        jdbc.update(
                "update customer_intake set assistant_message = ?, updated_at = ?, expires_at = ?, "
                        + "version = version + 1 where id = ?",
                assistantMessage,
                timestamp(now),
                timestamp(now.plus(Duration.ofDays(7))),
                intakeId);
        appendTranscript(intakeId, "AGENT", assistantMessage, now);
        return snapshot(load(customerId, intakeId), false);
    }

    private CustomerIntakeSnapshot completeCurrentOrder(
            String customerId, UUID intakeId, String completionMessage) {
        IntakeRow current = loadForUpdate(customerId, intakeId);
        if (current.pendingOrders().isEmpty()) {
            Instant now = clock.instant();
            jdbc.update(
                    "update customer_intake set status = 'CONFIRMED', assistant_message = ?, "
                            + "confirmed_at = coalesce(confirmed_at, ?), updated_at = ?, "
                            + "retention_state = 'COMPLETED', expires_at = null, archived_at = null, "
                            + "facts_changed = false, version = version + 1 "
                            + "where id = ?",
                    completionMessage,
                    timestamp(now),
                    timestamp(now),
                    intakeId);
            appendTranscript(intakeId, "AGENT", completionMessage, now);
            return snapshot(load(customerId, intakeId), false);
        }
        List<CustomerVisibleOrderSummary> remainingOrders =
                current.pendingOrders().stream()
                        .map(
                                order ->
                                        new CustomerVisibleOrderSummary(
                                                order.reference(),
                                                order.summary(),
                                                order.version()))
                        .toList();
        IntakeUnderstanding understanding =
                agent.understand(
                        new IntakeUnderstandingRequest(
                                current.originalMessage(),
                                remainingOrders,
                                null,
                                null,
                                List.of(),
                                List.of(),
                                List.of()));
        requireUnderstanding(understanding, remainingOrders);
        if (!remainingOrders
                .getFirst()
                .reference()
                .equals(understanding.candidateOrderReference())) {
            throw new IntakeAgentUnavailableException();
        }
        CustomerVisibleOrderSummary candidate = candidate(understanding, remainingOrders);
        String assistantMessage =
                completionMessage
                        + " 原始描述已保留，请重新确认下一订单与问题集合。"
                        + CustomerIntakeSafetyPolicy.assistantMessage(understanding);
        Instant now = clock.instant();
        jdbc.update(
                "update customer_intake set status = ?, candidate_order_reference = ?, "
                        + "candidate_order_version = ?, candidate_order_summary = ?, issue_kind = ?, "
                        + "issue_summary = ?, assistant_message = ?, updated_at = ?, expires_at = ?, "
                        + "version = version + 1 where id = ?",
                understanding.status(),
                understanding.candidateOrderReference(),
                candidate.version(),
                candidate.summary(),
                firstKind(understanding.issues()),
                firstSummary(understanding.issues()),
                assistantMessage,
                timestamp(now),
                timestamp(now.plus(Duration.ofDays(7))),
                intakeId);
        replaceIssues(intakeId, understanding.issues());
        replacePendingIssueKinds(intakeId, understanding.pendingIssueKinds());
        replacePendingOrders(intakeId, understanding.remainingOrderReferences(), remainingOrders);
        syncDuplicateMatches(
                intakeId,
                customerId,
                understanding.candidateOrderReference(),
                understanding.issues());
        appendTranscript(intakeId, "AGENT", assistantMessage, now);
        return snapshot(load(customerId, intakeId), false);
    }

    private CustomerIntakeSnapshot confirm(
            ReplyCustomerIntake command, IntakeRow current, String assistantMessage) {
        if (!"READY_TO_CONFIRM".equals(current.status())
                || current.orderReference() == null
                || current.issues().isEmpty()
                || !current.pendingIssueKinds().isEmpty()
                || !current.duplicateMatches().isEmpty()) {
            throw new IntakeNotReadyException();
        }
        CustomerVisibleOrderSummary authoritative =
                authoritativeOrderForConfirmation(command.customerId(), current.orderReference());
        if (!authoritative.version().equals(current.orderVersion())) {
            throw new IntakeCandidateStaleException();
        }
        UUID sharedRecordId = UUID.randomUUID();
        Instant now = clock.instant();
        jdbc.update(
                "insert into shared_intake_record "
                        + "(id, intake_id, customer_id, order_reference, original_message, customer_confirmation, confirmed_at) "
                        + "select ?, id, customer_id, candidate_order_reference, original_message, ?, ? "
                        + "from customer_intake where id = ?",
                sharedRecordId,
                command.message(),
                timestamp(now),
                command.intakeId());
        java.util.ArrayList<UUID> ticketIds = new java.util.ArrayList<>();
        int ordinal = 0;
        for (ProposedIntakeIssue issue : current.issues()) {
            ordinal++;
            TicketCreationResult created =
                    tickets.create(
                            new CreateCustomerTicket(
                                    command.customerId(),
                                    "intake-confirm:"
                                            + command.intakeId()
                                            + ":"
                                            + current.orderReference()
                                            + ":"
                                            + issue.kind(),
                                    current.orderReference(),
                                    issue.summary(),
                                    issue.kind()));
            ticketIds.add(created.ticketId());
            jdbc.update(
                    "insert into shared_intake_issue "
                            + "(id, shared_intake_record_id, ordinal, issue_kind, ticket_id) "
                            + "values (?, ?, ?, ?, ?)",
                    UUID.randomUUID(),
                    sharedRecordId,
                    ordinal,
                    issue.kind(),
                    created.ticketId());
        }
        jdbc.update(
                "update customer_intake set assistant_message = ?, ticket_id = coalesce(ticket_id, ?), shared_intake_record_id = ?, "
                        + "confirmed_at = ?, updated_at = ?, version = version + 1 where id = ?",
                assistantMessage,
                ticketIds.getFirst(),
                sharedRecordId,
                timestamp(now),
                timestamp(now),
                command.intakeId());
        return completeCurrentOrder(
                command.customerId(),
                command.intakeId(),
                "已确认，当前订单的 " + current.issues().size() + " 张客服工单已原子创建并开始独立处理。");
    }

    private List<CustomerVisibleOrderSummary> visibleOrders(String customerId) {
        return jdbc.query(
                "select order_reference, paid, cancelled, fully_refunded, delay_seconds, policy_version "
                        + "from synthetic_order where customer_id = ? order by order_reference",
                (rs, row) -> orderSummary(rs),
                customerId);
    }

    private CustomerVisibleOrderSummary authoritativeOrderForConfirmation(
            String customerId, String orderReference) {
        List<CustomerVisibleOrderSummary> rows =
                jdbc.query(
                        "select order_reference, paid, cancelled, fully_refunded, delay_seconds, policy_version "
                                + "from synthetic_order where customer_id = ? and order_reference = ? for update",
                        (rs, row) -> orderSummary(rs),
                        customerId,
                        orderReference);
        if (rows.isEmpty()) throw new IntakeCandidateStaleException();
        return rows.getFirst();
    }

    private static CustomerVisibleOrderSummary orderSummary(java.sql.ResultSet rs)
            throws java.sql.SQLException {
        String reference = rs.getString(1);
        boolean paid = rs.getBoolean(2);
        boolean cancelled = rs.getBoolean(3);
        boolean refunded = rs.getBoolean(4);
        long delaySeconds = rs.getLong(5);
        String policy = rs.getString(6);
        String summary =
                cancelled ? "已取消的合成订单" : refunded ? "已退款的合成订单" : paid ? "配送中的合成订单" : "待支付的合成订单";
        String version =
                StableParameterDigest.sha256(
                        reference,
                        Boolean.toString(paid),
                        Boolean.toString(cancelled),
                        Boolean.toString(refunded),
                        Long.toString(delaySeconds),
                        policy);
        return new CustomerVisibleOrderSummary(reference, summary, version);
    }

    private static void requireUnderstanding(
            IntakeUnderstanding understanding, List<CustomerVisibleOrderSummary> orders) {
        if (!"UNDERSTANDING".equals(understanding.intent())
                || !List.of("READY_TO_CONFIRM", "NEEDS_CLARIFICATION")
                        .contains(understanding.status())
                || ("READY_TO_CONFIRM".equals(understanding.status())
                        && (understanding.candidateOrderReference() == null
                                || understanding.issues().isEmpty()
                                || !understanding.pendingIssueKinds().isEmpty()))
                || understanding.pendingIssueKinds().stream()
                        .anyMatch(
                                kind ->
                                        !List.of(
                                                                "LOGISTICS_DELAY",
                                                                "PACKAGE_NOT_RECEIVED",
                                                                "DUPLICATE_CHARGE")
                                                        .contains(kind)
                                                || understanding.issues().stream()
                                                        .anyMatch(
                                                                issue -> issue.kind().equals(kind)))
                || understanding.remainingOrderReferences().stream().distinct().count()
                        != understanding.remainingOrderReferences().size()
                || understanding.remainingOrderReferences().stream()
                        .anyMatch(
                                reference ->
                                        reference.equals(understanding.candidateOrderReference())
                                                || orders.stream()
                                                        .noneMatch(
                                                                order ->
                                                                        order.reference()
                                                                                .equals(reference)))
                || (understanding.candidateOrderReference() != null
                        && orders.stream()
                                .noneMatch(
                                        order ->
                                                order.reference()
                                                        .equals(
                                                                understanding
                                                                        .candidateOrderReference())))) {
            throw new IntakeAgentUnavailableException();
        }
    }

    private static CustomerVisibleOrderSummary candidate(
            IntakeUnderstanding understanding, List<CustomerVisibleOrderSummary> orders) {
        if (understanding.candidateOrderReference() == null) return null;
        return orders.stream()
                .filter(order -> order.reference().equals(understanding.candidateOrderReference()))
                .findFirst()
                .orElseThrow(IntakeAgentUnavailableException::new);
    }

    private IntakeRow loadForUpdate(String customerId, UUID intakeId) {
        List<IntakeRow> rows =
                jdbc.query(
                        "select "
                                + intakeColumns()
                                + " from customer_intake "
                                + "where id = ? and customer_id = ? for update",
                        (rs, row) -> map(rs),
                        intakeId,
                        customerId);
        if (rows.isEmpty()) throw new IntakeNotFoundException();
        return enrich(rows.getFirst());
    }

    private IntakeRow load(String customerId, UUID intakeId) {
        List<IntakeRow> rows =
                jdbc.query(
                        "select "
                                + intakeColumns()
                                + " from customer_intake where id = ? and customer_id = ?",
                        (rs, row) -> map(rs),
                        intakeId,
                        customerId);
        if (rows.isEmpty()) throw new IntakeNotFoundException();
        return enrich(rows.getFirst());
    }

    private IntakeRow enrich(IntakeRow row) {
        List<ProposedIntakeIssue> issues =
                jdbc.query(
                        "select issue_kind, issue_summary from customer_intake_issue "
                                + "where intake_id = ? order by ordinal",
                        (rs, number) -> new ProposedIntakeIssue(rs.getString(1), rs.getString(2)),
                        row.id());
        List<UUID> ticketIds =
                jdbc.query(
                        "select issue.ticket_id from shared_intake_record record "
                                + "join shared_intake_issue issue on issue.shared_intake_record_id = record.id "
                                + "where record.intake_id = ? order by record.confirmed_at, issue.ordinal",
                        (rs, number) -> rs.getObject(1, UUID.class),
                        row.id());
        List<String> pendingIssueKinds =
                jdbc.query(
                        "select issue_kind from customer_intake_pending_issue "
                                + "where intake_id = ? order by ordinal",
                        (rs, number) -> rs.getString(1),
                        row.id());
        List<PendingOrder> pendingOrders =
                jdbc.query(
                        "select order_reference, order_version, order_summary "
                                + "from customer_intake_pending_order where intake_id = ? order by ordinal",
                        (rs, number) ->
                                new PendingOrder(rs.getString(1), rs.getString(2), rs.getString(3)),
                        row.id());
        List<DuplicateIntakeMatch> duplicateMatches =
                jdbc.query(
                        "select existing_ticket_id, issue_kind, issue_summary, lifecycle_state "
                                + "from customer_intake_duplicate_match "
                                + "where intake_id = ? and resolution is null order by issue_kind, existing_ticket_id",
                        (rs, number) ->
                                new DuplicateIntakeMatch(
                                        rs.getObject(1, UUID.class),
                                        rs.getString(2),
                                        rs.getString(3),
                                        rs.getString(4)),
                        row.id());
        List<UUID> routedTicketIds =
                jdbc.query(
                        "select ticket_id from customer_intake_routed_ticket "
                                + "where intake_id = ? order by routed_at, ticket_id",
                        (rs, number) -> rs.getObject(1, UUID.class),
                        row.id());
        Integer completedOrderCount =
                jdbc.queryForObject(
                        "select count(*) from ("
                                + "select order_reference from shared_intake_record where intake_id = ? "
                                + "union select order_reference from customer_intake_routed_ticket where intake_id = ?"
                                + ") completed_orders",
                        Integer.class,
                        row.id(),
                        row.id());
        return new IntakeRow(
                row.id(),
                row.startDigest(),
                row.originalMessage(),
                row.status(),
                row.orderReference(),
                row.orderVersion(),
                row.orderSummary(),
                row.issueKind(),
                row.issueSummary(),
                row.assistantMessage(),
                row.ticketId(),
                row.sharedIntakeRecordId(),
                row.retentionState(),
                row.version(),
                row.expiresAt(),
                row.archivedAt(),
                row.factsChanged(),
                issues,
                pendingIssueKinds,
                ticketIds,
                pendingOrders,
                duplicateMatches,
                routedTicketIds,
                completedOrderCount == null ? 0 : completedOrderCount);
    }

    private void replaceIssues(UUID intakeId, List<ProposedIntakeIssue> issues) {
        jdbc.update("delete from customer_intake_issue where intake_id = ?", intakeId);
        int ordinal = 0;
        for (ProposedIntakeIssue issue : issues) {
            ordinal++;
            jdbc.update(
                    "insert into customer_intake_issue (intake_id, ordinal, issue_kind, issue_summary) "
                            + "values (?, ?, ?, ?)",
                    intakeId,
                    ordinal,
                    issue.kind(),
                    issue.summary());
        }
    }

    private void replacePendingIssueKinds(UUID intakeId, List<String> pendingIssueKinds) {
        jdbc.update("delete from customer_intake_pending_issue where intake_id = ?", intakeId);
        int ordinal = 0;
        for (String kind : pendingIssueKinds) {
            ordinal++;
            jdbc.update(
                    "insert into customer_intake_pending_issue (intake_id, ordinal, issue_kind) "
                            + "values (?, ?, ?)",
                    intakeId,
                    ordinal,
                    kind);
        }
    }

    private void replacePendingOrders(
            UUID intakeId,
            List<String> remainingOrderReferences,
            List<CustomerVisibleOrderSummary> visibleOrders) {
        jdbc.update("delete from customer_intake_pending_order where intake_id = ?", intakeId);
        int ordinal = 0;
        for (String reference : remainingOrderReferences) {
            CustomerVisibleOrderSummary order =
                    visibleOrders.stream()
                            .filter(candidate -> candidate.reference().equals(reference))
                            .findFirst()
                            .orElseThrow(IntakeAgentUnavailableException::new);
            ordinal++;
            jdbc.update(
                    "insert into customer_intake_pending_order "
                            + "(intake_id, ordinal, order_reference, order_version, order_summary) "
                            + "values (?, ?, ?, ?, ?)",
                    intakeId,
                    ordinal,
                    order.reference(),
                    order.version(),
                    order.summary());
        }
    }

    private void syncDuplicateMatches(
            UUID intakeId,
            String customerId,
            String orderReference,
            List<ProposedIntakeIssue> issues) {
        jdbc.update(
                "delete from customer_intake_duplicate_match where intake_id = ? and resolution is null",
                intakeId);
        if (orderReference == null) return;
        for (ProposedIntakeIssue issue : issues) {
            jdbc.update(
                    "insert into customer_intake_duplicate_match "
                            + "(intake_id, issue_kind, existing_ticket_id, issue_summary, lifecycle_state) "
                            + "select ?, ?, id, ?, lifecycle_state from support_ticket "
                            + "where customer_id = ? and order_reference = ? and issue_kind = ? "
                            + "on conflict do nothing",
                    intakeId,
                    issue.kind(),
                    issue.summary(),
                    customerId,
                    orderReference,
                    issue.kind());
        }
    }

    private IntakeRow requireActive(IntakeRow current) {
        IntakeRow authoritative = archiveIfExpired(current);
        if ("ARCHIVED".equals(authoritative.retentionState())) {
            throw new IntakeArchivedException();
        }
        return authoritative;
    }

    private static void requireVersion(IntakeRow current, long expectedVersion) {
        if (current.version() != expectedVersion) {
            throw new IntakeVersionConflictException();
        }
    }

    private IntakeRow archiveIfExpired(IntakeRow current) {
        Instant now = clock.instant();
        if ("ACTIVE".equals(current.retentionState())
                && current.expiresAt() != null
                && !now.isBefore(current.expiresAt())) {
            jdbc.update(
                    "update customer_intake set retention_state = 'ARCHIVED', archived_at = ?, "
                            + "updated_at = ?, version = version + 1 "
                            + "where id = ? and version = ? and retention_state = 'ACTIVE'",
                    timestamp(now),
                    timestamp(now),
                    current.id(),
                    current.version());
            return loadForUpdateById(current.id());
        }
        return current;
    }

    private IntakeRow loadForUpdateById(UUID intakeId) {
        List<IntakeRow> rows =
                jdbc.query(
                        "select "
                                + intakeColumns()
                                + " from customer_intake where id = ? for update",
                        (rs, row) -> map(rs),
                        intakeId);
        if (rows.isEmpty()) throw new IntakeNotFoundException();
        return enrich(rows.getFirst());
    }

    private boolean factsChanged(
            IntakeRow archived,
            List<CustomerVisibleOrderSummary> currentOrders,
            CustomerVisibleOrderSummary restoredCandidate) {
        if (archived.orderReference() != null) {
            CustomerVisibleOrderSummary currentCandidate =
                    currentOrders.stream()
                            .filter(order -> order.reference().equals(archived.orderReference()))
                            .findFirst()
                            .orElse(null);
            if (currentCandidate == null
                    || !currentCandidate.version().equals(archived.orderVersion())) {
                return true;
            }
        }
        if (restoredCandidate != null
                && archived.orderReference() != null
                && !restoredCandidate.reference().equals(archived.orderReference())) {
            return true;
        }
        return archived.pendingOrders().stream()
                .anyMatch(
                        pending ->
                                currentOrders.stream()
                                        .noneMatch(
                                                order ->
                                                        order.reference()
                                                                        .equals(pending.reference())
                                                                && order.version()
                                                                        .equals(
                                                                                pending
                                                                                        .version())));
    }

    private RecoverableCustomerIntake recoverable(IntakeRow row, boolean replayed) {
        List<IntakeConversationMessage> messages =
                jdbc.query(
                        "select author, body, created_at from customer_intake_transcript "
                                + "where intake_id = ? order by ordinal",
                        (rs, number) ->
                                new IntakeConversationMessage(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getTimestamp(3).toInstant()),
                        row.id());
        return new RecoverableCustomerIntake(
                snapshot(row, replayed),
                row.version(),
                row.retentionState(),
                row.expiresAt(),
                row.archivedAt(),
                row.factsChanged(),
                messages);
    }

    private String latestCustomerMessage(UUID intakeId, String fallback) {
        return jdbc
                .query(
                        "select body from customer_intake_transcript "
                                + "where intake_id = ? and author = 'CUSTOMER' order by ordinal desc limit 1",
                        (rs, row) -> rs.getString(1),
                        intakeId)
                .stream()
                .findFirst()
                .orElse(fallback);
    }

    private void appendTranscript(UUID intakeId, String author, String body, Instant sentAt) {
        Long nextOrdinal =
                jdbc.queryForObject(
                        "select coalesce(max(ordinal), 0) + 1 from customer_intake_transcript where intake_id = ?",
                        Long.class,
                        intakeId);
        jdbc.update(
                "insert into customer_intake_transcript "
                        + "(id, intake_id, ordinal, author, body, created_at) values (?, ?, ?, ?, ?, ?)",
                UUID.randomUUID(),
                intakeId,
                nextOrdinal == null ? 1L : nextOrdinal,
                author,
                body,
                timestamp(sentAt));
    }

    private static Timestamp timestamp(Instant instant) {
        return Timestamp.from(instant);
    }

    private static String firstKind(List<ProposedIntakeIssue> issues) {
        return issues.isEmpty() ? null : issues.getFirst().kind();
    }

    private static String firstSummary(List<ProposedIntakeIssue> issues) {
        return issues.isEmpty() ? null : issues.getFirst().summary();
    }

    private static String intakeColumns() {
        return "id, start_digest, original_message, status, candidate_order_reference, candidate_order_version, "
                + "candidate_order_summary, issue_kind, issue_summary, assistant_message, ticket_id, shared_intake_record_id, "
                + "retention_state, version, expires_at, archived_at, facts_changed";
    }

    private static IntakeRow map(java.sql.ResultSet rs) throws java.sql.SQLException {
        UUID intakeId = rs.getObject(1, UUID.class);
        return new IntakeRow(
                intakeId,
                rs.getString(2),
                rs.getString(3),
                rs.getString(4),
                rs.getString(5),
                rs.getString(6),
                rs.getString(7),
                rs.getString(8),
                rs.getString(9),
                rs.getString(10),
                rs.getObject(11, UUID.class),
                rs.getObject(12, UUID.class),
                rs.getString(13),
                rs.getLong(14),
                rs.getTimestamp(15) == null ? null : rs.getTimestamp(15).toInstant(),
                rs.getTimestamp(16) == null ? null : rs.getTimestamp(16).toInstant(),
                rs.getBoolean(17),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                0);
    }

    private static CustomerIntakeSnapshot snapshot(IntakeRow row, boolean replayed) {
        List<ProposedIntakeIssue> issues = row.issues();
        List<UUID> ticketIds = row.ticketIds();
        return new CustomerIntakeSnapshot(
                row.id(),
                row.status(),
                row.orderReference(),
                row.orderSummary(),
                issues,
                row.assistantMessage(),
                ticketIds,
                row.sharedIntakeRecordId(),
                row.duplicateMatches(),
                row.routedTicketIds(),
                row.pendingOrders().size(),
                row.completedOrderCount(),
                row.version(),
                replayed);
    }

    private record MessageIdentity(String digest) {}

    private record IntakeRow(
            UUID id,
            String startDigest,
            String originalMessage,
            String status,
            String orderReference,
            String orderVersion,
            String orderSummary,
            String issueKind,
            String issueSummary,
            String assistantMessage,
            UUID ticketId,
            UUID sharedIntakeRecordId,
            String retentionState,
            long version,
            Instant expiresAt,
            Instant archivedAt,
            boolean factsChanged,
            List<ProposedIntakeIssue> issues,
            List<String> pendingIssueKinds,
            List<UUID> createdTicketIds,
            List<PendingOrder> pendingOrders,
            List<DuplicateIntakeMatch> duplicateMatches,
            List<UUID> routedTicketIds,
            int completedOrderCount) {
        List<UUID> ticketIds() {
            return createdTicketIds;
        }
    }

    private record PendingOrder(String reference, String version, String summary) {}

    private record RestoreIdentity(String digest) {}
}
