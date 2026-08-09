package com.stellogic.customeragent.reliability;

import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public final class TicketAuthorityLock {
    private final JdbcTemplate jdbc;

    public TicketAuthorityLock(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void acquire(UUID ticketId) {
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                resultSet -> null,
                ticketId + "\nBUSINESS_AUTHORITY");
    }
}
