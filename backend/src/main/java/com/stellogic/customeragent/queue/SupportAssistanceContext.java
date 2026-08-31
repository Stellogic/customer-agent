package com.stellogic.customeragent.queue;

import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/** 只读取客服当前责任；不把工作台详情访问权当作 HUMAN 辅助授权。 */
@Service
class SupportAssistanceContext {
    private final JdbcTemplate jdbc;
    private final SupportWorkbenchProjectionService workbench;

    SupportAssistanceContext(JdbcTemplate jdbc, SupportWorkbenchProjectionService workbench) {
        this.jdbc = jdbc;
        this.workbench = workbench;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    Snapshot load(String supportId, UUID ticketId) {
        var details = workbench.details(supportId, ticketId);
        if (details.handlingMode() != SupportHandlingMode.HUMAN) {
            throw new SupportTicketNotFoundException();
        }
        UUID assignmentId = jdbc.queryForObject(
                "select id from support_assignment where ticket_id = ? and support_id = ? and status = 'ACTIVE'",
                UUID.class, ticketId, supportId);
        var messages = details.publicConversation();
        // 只提供近期公开沟通，不传 audit、主体身份或完整历史载荷。
        return new Snapshot(ticketId, assignmentId, details.description(),
                List.copyOf(messages.subList(Math.max(0, messages.size() - 20), messages.size())),
                details.investigationFacts());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    void requireAssignment(String supportId, UUID ticketId, UUID assignmentId) {
        Snapshot current = load(supportId, ticketId);
        if (!current.assignmentId().equals(assignmentId)) throw new SupportTicketNotFoundException();
    }

    record Snapshot(UUID ticketId, UUID assignmentId, String description,
            List<SupportConversationMessage> messages, List<SupportInvestigationFact> facts) {}
}
