package com.stellogic.customeragent.clarification;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
class AgentResumeStore {
    private final JdbcTemplate jdbc;

    AgentResumeStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional
    Optional<PendingResume> claim() {
        List<PendingResume> pending = jdbc.query(
                "select r.resume_request_id, r.generation_id, c.ticket_id, r.thread_id, "
                        + "r.clarification_request_id, r.answer_digest, r.answer_summary "
                        + "from agent_resume_request r "
                        + "join customer_clarification_request c on c.id = r.clarification_request_id "
                        + "join agent_processing_generation g on g.id = r.generation_id "
                        + "join support_ticket t on t.id = g.ticket_id "
                        + "where r.status in ('PENDING', 'RETRY', 'SUBMITTING', 'SUBMITTED') "
                        + "and r.next_attempt_at <= current_timestamp and g.status = 'ACTIVE' "
                        + "and t.handling_mode = 'AGENT' and not t.customer_human_preference "
                        + "order by r.created_at for update of r skip locked limit 1",
                (rs, row) -> new PendingResume(
                        rs.getObject(1, UUID.class), rs.getObject(2, UUID.class), rs.getObject(3, UUID.class),
                        rs.getObject(4, UUID.class), rs.getObject(5, UUID.class), rs.getString(6), rs.getString(7)));
        if (pending.isEmpty()) return Optional.empty();
        PendingResume resume = pending.getFirst();
        jdbc.update(
                "update agent_resume_request set status = 'SUBMITTING', attempts = attempts + 1, "
                        + "next_attempt_at = current_timestamp + interval '5 seconds', last_error = null "
                        + "where resume_request_id = ?",
                resume.resumeRequestId());
        return Optional.of(resume);
    }

    @Transactional
    void submitted(UUID resumeRequestId, String runId) {
        jdbc.update(
                "update agent_resume_request set status = 'SUBMITTED', server_run_id = ?, "
                        + "submitted_at = current_timestamp, last_error = null "
                        + "where resume_request_id = ? and status <> 'COMPLETED'",
                runId, resumeRequestId);
    }

    @Transactional
    void retry(UUID resumeRequestId, String error) {
        String bounded = error == null ? "unknown resume response" : error.substring(0, Math.min(error.length(), 500));
        jdbc.update(
                "update agent_resume_request set status = 'RETRY', next_attempt_at = current_timestamp + interval '1 second', "
                        + "last_error = ? where resume_request_id = ? and status <> 'COMPLETED'",
                bounded, resumeRequestId);
    }

    record PendingResume(
            UUID resumeRequestId, UUID generationId, UUID ticketId, UUID threadId,
            UUID clarificationRequestId, String answerDigest, String answerSummary) {}
}
