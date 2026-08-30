package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.sla.SlaService;
import com.stellogic.customeragent.ticket.TicketResolutionTransition;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

@Service
public class AutoResolutionService {
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TicketAuthorityLock authorityLock;
    private final JdbcAgentInvestigationService investigation;
    private final TicketResolutionTransition resolution;
    private final SlaService sla;
    private final ObjectMapper json;

    AutoResolutionService(JdbcTemplate jdbc, Clock clock, TicketAuthorityLock authorityLock,
            JdbcAgentInvestigationService investigation, TicketResolutionTransition resolution,
            SlaService sla, ObjectMapper json) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.authorityLock = authorityLock;
        this.investigation = investigation;
        this.resolution = resolution;
        this.sla = sla;
        this.json = json;
    }

    @Transactional(readOnly = true)
    public List<UUID> dueTicketIds() {
        return jdbc.query("select ticket_id from ticket_auto_resolution where status = 'PENDING' "
                        + "and due_at <= ? order by due_at, ticket_id",
                (rs, row) -> rs.getObject(1, UUID.class), Timestamp.from(clock.instant()));
    }

    @Transactional
    public void resolveIfDue(UUID ticketId) {
        authorityLock.acquire(ticketId);
        // The same ticket lock serializes accepted customer messages and deadline decisions.
        jdbc.query("select id from support_ticket where id = ? for update", rs -> null, ticketId);
        Instant now = clock.instant();
        List<Candidate> candidates = jdbc.query(
                "select generation_id, policy_version, scenario, conclusion::text, customer_message_sequence, reply_message_id "
                        + "from ticket_auto_resolution where ticket_id = ? and status = 'PENDING' and due_at <= ? for update",
                (rs, row) -> new Candidate(rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3),
                        json.readValue(rs.getString(4), InvestigationConclusion.class), rs.getLong(5), rs.getObject(6, UUID.class)),
                ticketId, Timestamp.from(now));
        if (candidates.isEmpty()) return;
        Candidate candidate = candidates.getFirst();
        Boolean current = jdbc.queryForObject(
                "select exists(select 1 from support_ticket t join agent_processing_generation g on g.ticket_id = t.id "
                        + "join public_message m on m.id = ? and m.ticket_id = t.id and m.author = 'AGENT' and m.body = ? "
                        + "where t.id = ? and t.lifecycle_state = 'INVESTIGATING' and t.handling_mode = 'AGENT' "
                        + "and not t.customer_human_preference and g.id = ? and g.status = 'COMPLETED' "
                        + "and g.generation_number = (select max(generation_number) from agent_processing_generation where ticket_id = t.id) "
                        + "and ? = (select coalesce(max(message_sequence), 0) from public_message where ticket_id = t.id and author = 'CUSTOMER') "
                        + "and not exists(select 1 from agent_public_reply_stream where generation_id = g.id and status <> 'COMPLETED'))",
                Boolean.class, candidate.replyId(), candidate.conclusion().customerReply().body(), ticketId,
                candidate.generationId(), candidate.customerSequence());
        if (!Boolean.TRUE.equals(current) || !AutoResolutionPolicy.VERSION.equals(candidate.policyVersion())
                || !candidate.scenario().equals(investigation.revalidateAutoResolution(
                        ticketId, candidate.generationId(), candidate.conclusion()))) {
            changeStatus(ticketId, "REEVALUATING", clock.instant());
            return;
        }
        now = clock.instant();
        sla.evaluateTicket(ticketId, now);
        if (resolution.fromAgentInvestigation(ticketId, now) != 1)
            throw new IllegalStateException("locked auto-resolution ticket lost authority");
        changeStatus(ticketId, "RESOLVED", now);
        jdbc.update("insert into customer_public_event (ticket_id, epoch, sequence, event_type, payload, occurred_at) "
                        + "select ?, 'customer-public-v1', coalesce(max(sequence), 0) + 1, 'TICKET_RESOLVED', "
                        + "jsonb_build_object('lifecycleState', 'RESOLVED'), ? from customer_public_event "
                        + "where ticket_id = ? and epoch = 'customer-public-v1'",
                ticketId, Timestamp.from(now), ticketId);
        jdbc.update("insert into audit_event (ticket_id, event_type, actor_id, occurred_at) "
                        + "values (?, 'TICKET_RESOLVED', 'spring-system', ?)", ticketId, Timestamp.from(now));
    }

    @Transactional
    public void cancel(String customerId, UUID ticketId, Instant candidateDueAt, long candidateGeneration) {
        authorityLock.acquire(ticketId);
        List<String> tickets = jdbc.query("select lifecycle_state from support_ticket where id = ? and customer_id = ? for update",
                (rs, row) -> rs.getString(1), ticketId, customerId);
        if (tickets.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "ticket not found");
        List<String> states = jdbc.query("select a.status from ticket_auto_resolution a "
                        + "join agent_processing_generation g on g.id = a.generation_id "
                        + "where a.ticket_id = ? and a.due_at = ? and g.generation_number = ? for update of a",
                (rs, row) -> rs.getString(1), ticketId, Timestamp.from(candidateDueAt), candidateGeneration);
        if (states.isEmpty() || "RESOLVED".equals(states.getFirst()))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "candidate changed; reload snapshot");
        if ("CANCELLED".equals(states.getFirst())) return;
        changeStatus(ticketId, "CANCELLED", clock.instant());
    }

    private void changeStatus(UUID ticketId, String status, Instant now) {
        jdbc.update("update ticket_auto_resolution set status = ?, updated_at = ? where ticket_id = ?",
                status, Timestamp.from(now), ticketId);
        jdbc.update("insert into audit_event (ticket_id, event_type, actor_id, occurred_at) values (?, ?, 'spring-system', ?)",
                ticketId, "AUTO_RESOLUTION_" + status, Timestamp.from(now));
    }

    private record Candidate(UUID generationId, String policyVersion, String scenario,
            InvestigationConclusion conclusion, long customerSequence, UUID replyId) {}
}
