package com.stellogic.customeragent.investigation;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class AgentSubmissionStoreTest {
    @Test
    void claimUsesOneDatabaseClockForEligibility() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        when(jdbc.query(
                        any(String.class),
                        org.mockito.ArgumentMatchers
                                .<RowMapper<AgentSubmissionStore.PendingSubmission>>any()))
                .thenReturn(List.of());
        var store = new AgentSubmissionStore(jdbc);

        store.claim();

        verify(jdbc)
                .query(
                        contains("next_attempt_at <= current_timestamp"),
                        org.mockito.ArgumentMatchers
                                .<RowMapper<AgentSubmissionStore.PendingSubmission>>any());
    }
}
