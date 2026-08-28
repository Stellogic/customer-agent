package com.stellogic.customeragent.investigation;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
class AgentSubmissionStore {
    private final JdbcTemplate jdbc;

    AgentSubmissionStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional
    Optional<PendingSubmission> claim() {
        List<PendingSubmission> pending =
                jdbc.query(
                        "select s.submission_request_id, s.generation_id, g.ticket_id, s.thread_id, t.issue_kind "
                                + "from agent_submission s join agent_processing_generation g on g.id = s.generation_id "
                                + "join support_ticket t on t.id = g.ticket_id "
                                + "where s.status in ('PENDING', 'RETRY', 'SUBMITTING', 'SUBMITTED') "
                                + "and s.next_attempt_at <= current_timestamp "
                                + "and g.status = 'ACTIVE' order by s.created_at for update skip locked limit 1",
                        (rs, row) ->
                                new PendingSubmission(
                                        rs.getObject(1, UUID.class),
                                        rs.getObject(2, UUID.class),
                                        rs.getObject(3, UUID.class),
                                        rs.getObject(4, UUID.class),
                                        rs.getString(5)));
        if (pending.isEmpty()) return Optional.empty();
        PendingSubmission submission = pending.getFirst();
        jdbc.update(
                "update agent_submission set status = 'SUBMITTING', attempts = attempts + 1, "
                        + "next_attempt_at = current_timestamp + interval '5 seconds', last_error = null "
                        + "where submission_request_id = ?",
                submission.submissionRequestId());
        return Optional.of(submission);
    }

    @Transactional
    void submitted(UUID submissionRequestId) {
        jdbc.update(
                "update agent_submission set status = 'SUBMITTED', submitted_at = current_timestamp, last_error = null "
                        + "where submission_request_id = ? and status <> 'COMPLETED'",
                submissionRequestId);
    }

    @Transactional
    void retry(UUID submissionRequestId, String error) {
        String bounded =
                error == null
                        ? "unknown submission response"
                        : error.substring(0, Math.min(error.length(), 500));
        jdbc.update(
                "update agent_submission set status = 'RETRY', next_attempt_at = current_timestamp + interval '1 second', "
                        + "last_error = ? where submission_request_id = ? and status <> 'COMPLETED'",
                bounded,
                submissionRequestId);
    }

    record PendingSubmission(
            UUID submissionRequestId,
            UUID generationId,
            UUID ticketId,
            UUID threadId,
            String issueKind) {}
}
