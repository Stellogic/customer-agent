package com.stellogic.customeragent.queue;

import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
class SharedSupportQueueProjectionService {
    private final JdbcTemplate jdbc;

    SharedSupportQueueProjectionService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional(readOnly = true)
    List<SharedQueueSummary> queue() {
        return jdbc.query(
                "select q.ticket_id, t.lifecycle_state, t.handling_mode, "
                        + "array_agg(q.reason_code order by q.reason_code), min(q.entered_at) "
                        + "from shared_support_queue_entry q join support_ticket t on t.id = q.ticket_id "
                        + "group by q.ticket_id, t.lifecycle_state, t.handling_mode "
                        + "order by min(q.entered_at), q.ticket_id",
                (rs, row) ->
                        new SharedQueueSummary(
                                rs.getObject(1, UUID.class),
                                rs.getString(2),
                                rs.getString(3),
                                List.of((String[]) rs.getArray(4).getArray()),
                                rs.getTimestamp(5).toInstant()));
    }
}

record SharedQueueSummary(
        UUID ticketId,
        String lifecycleState,
        String handlingMode,
        List<String> reasonCodes,
        Instant enteredAt) {}
