package com.stellogic.customeragent.queue;

import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/** 短事务申请一次执行权；检索和模型不在本事务中运行。 */
@Service
class SupportAssistanceRequests {
    private final JdbcTemplate jdbc;
    private final SupportAssistanceContext context;
    private final ObjectMapper json;

    SupportAssistanceRequests(JdbcTemplate jdbc, SupportAssistanceContext context, ObjectMapper json) {
        this.jdbc = jdbc;
        this.context = context;
        this.json = json;
    }

    @Transactional
    SupportAssistanceReceipt begin(String supportId, UUID ticketId, SupportAssistanceRequest request) {
        lockTicket(ticketId);
        var input = context.load(supportId, ticketId);
        if (!input.assignmentId().equals(request.assignmentId())) throw new SupportTicketNotFoundException();
        int inserted = jdbc.update("""
                insert into support_assistance_request
                (support_id, request_id, ticket_id, assignment_id, kind, query, input, status)
                values (?, ?, ?, ?, ?, ?, ?::jsonb, 'PENDING')
                on conflict (support_id, request_id) do nothing
                """, supportId, request.requestId(), ticketId, request.assignmentId(),
                request.kind().name(), request.query(), json.writeValueAsString(input));
        var stored = find(supportId, request.requestId());
        if (!stored.ticketId().equals(ticketId) || !stored.assignmentId().equals(request.assignmentId())
                || stored.kind() != request.kind() || !stored.query().equals(request.query())) {
            throw new SupportAssistanceConflictException();
        }
        return receipt(stored, inserted == 1, input);
    }

    @Transactional(readOnly = true)
    SupportAssistanceReceipt read(String supportId, UUID ticketId, UUID requestId) {
        var stored = find(supportId, requestId);
        if (!stored.ticketId().equals(ticketId)) throw new SupportTicketNotFoundException();
        context.requireAssignment(supportId, ticketId, stored.assignmentId());
        return receipt(stored, false, null);
    }

    @Transactional
    void recordModelAudit(String supportId, UUID requestId, String auditJson) {
        // 即使生成途中撤权，也保留已发生/未确认的调用成本证据；这不是结果访问授权。
        jdbc.update("update support_assistance_request set model_audit = ?::jsonb where support_id = ? and request_id = ?",
                auditJson, supportId, requestId);
    }

    @Transactional
    void finish(String supportId, UUID ticketId, UUID requestId, String resultJson, boolean failed) {
        lockTicket(ticketId);
        var stored = find(supportId, requestId);
        if (!stored.ticketId().equals(ticketId)) throw new SupportTicketNotFoundException();
        context.requireAssignment(supportId, ticketId, stored.assignmentId());
        jdbc.update("""
                update support_assistance_request set status = ?, result = ?::jsonb,
                completed_at = clock_timestamp()
                where support_id = ? and request_id = ? and status = 'PENDING'
                """, failed ? "FAILED" : "COMPLETED", resultJson, supportId, requestId);
    }

    private Stored find(String supportId, UUID requestId) {
        var rows = jdbc.query("""
                select ticket_id, assignment_id, request_id, kind, query, status, result::text
                from support_assistance_request where support_id = ? and request_id = ?
                """, (rs, row) -> new Stored(rs.getObject(1, UUID.class), rs.getObject(2, UUID.class),
                rs.getObject(3, UUID.class), SupportAssistanceKind.valueOf(rs.getString(4)),
                rs.getString(5), rs.getString(6), rs.getString(7)), supportId, requestId);
        if (rows.isEmpty()) throw new SupportTicketNotFoundException();
        return rows.getFirst();
    }

    private void lockTicket(UUID ticketId) {
        jdbc.query("select id from support_ticket where id = ? for update", rs -> null, ticketId);
    }

    private static SupportAssistanceReceipt receipt(Stored row, boolean execute, SupportAssistanceContext.Snapshot input) {
        return new SupportAssistanceReceipt(row.ticketId(), row.assignmentId(), row.requestId(), row.kind(),
                row.status(), row.resultJson(), execute, input);
    }

    private record Stored(UUID ticketId, UUID assignmentId, UUID requestId, SupportAssistanceKind kind,
            String query, String status, String resultJson) {}
}
