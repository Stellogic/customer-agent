package com.stellogic.customeragent.group;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
class OrderTicketGroupService {
    private final JdbcTemplate jdbc;

    OrderTicketGroupService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    List<CustomerOrderTicketGroup> customerGroups(String customerId) {
        List<TicketRow> rows =
                jdbc.query(
                        "select t.order_reference, t.id, t.issue_kind, t.lifecycle_state, t.handling_mode, "
                                + "c.public_question, exists (select 1 from compensation_proposal_revision p "
                                + "where p.ticket_id = t.id) from support_ticket t "
                                + "left join customer_clarification_request c on c.ticket_id = t.id and c.status = 'OPEN' "
                                + "where t.customer_id = ? order by t.order_reference, t.created_at, t.id",
                        (rs, row) ->
                                new TicketRow(
                                        rs.getString(1),
                                        rs.getObject(2, UUID.class),
                                        rs.getString(3),
                                        rs.getString(4),
                                        rs.getString(5),
                                        rs.getString(6),
                                        rs.getBoolean(7)),
                        customerId);
        LinkedHashMap<String, GroupBuilder> groups = new LinkedHashMap<>();
        for (TicketRow row : rows) {
            GroupBuilder group =
                    groups.computeIfAbsent(row.orderReference(), ignored -> new GroupBuilder());
            boolean pending = row.clarificationQuestion() != null;
            group.tickets.add(
                    new OrderTicketSummary(
                            row.ticketId(),
                            row.issueKind(),
                            row.lifecycleState(),
                            row.handlingMode(),
                            controlledProgress(row),
                            pending,
                            row.compensationFlowExists()));
            if (pending) {
                group.pendingItems.add(
                        new PendingCustomerItem(
                                row.ticketId(), "CLARIFICATION", row.clarificationQuestion()));
            }
        }
        return groups.entrySet().stream()
                .map(
                        entry ->
                                new CustomerOrderTicketGroup(
                                        entry.getKey(),
                                        List.copyOf(entry.getValue().tickets),
                                        List.copyOf(entry.getValue().pendingItems)))
                .toList();
    }

    private static String controlledProgress(TicketRow row) {
        if (row.clarificationQuestion() != null) return "WAITING_FOR_CUSTOMER";
        if ("CLOSED".equals(row.lifecycleState())) return "CLOSED";
        if ("RESOLVED".equals(row.lifecycleState())) return "RESOLVED";
        if ("WAITING_FOR_EXTERNAL".equals(row.lifecycleState())) return "WAITING_FOR_EXTERNAL";
        return "HUMAN".equals(row.handlingMode()) ? "HUMAN_HANDLING" : "AGENT_PROCESSING";
    }

    private record TicketRow(
            String orderReference,
            UUID ticketId,
            String issueKind,
            String lifecycleState,
            String handlingMode,
            String clarificationQuestion,
            boolean compensationFlowExists) {}

    private static final class GroupBuilder {
        private final List<OrderTicketSummary> tickets = new ArrayList<>();
        private final List<PendingCustomerItem> pendingItems = new ArrayList<>();
    }
}
