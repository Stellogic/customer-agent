package com.stellogic.customeragent.approval;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.handoff.HumanHandoffService;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import tools.jackson.databind.ObjectMapper;

class JdbcApprovalServiceTest {
    @SuppressWarnings("unchecked")
    @Test
    void queueResamplesAuthoritativeTimeAfterPotentiallyBlockingExpiry() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        Clock clock = org.mockito.Mockito.mock(Clock.class);
        CompensationProposalExpiry proposalExpiry =
                org.mockito.Mockito.mock(CompensationProposalExpiry.class);
        Instant beforeWait = Instant.parse("2026-08-13T00:00:00Z");
        Instant afterWait = Instant.parse("2026-08-13T00:00:01Z");
        when(clock.instant()).thenReturn(beforeWait, afterWait);
        when(jdbc.query(
                        contains("from compensation_proposal_revision"),
                        any(RowMapper.class),
                        any(Object[].class)))
                .thenReturn(List.of());
        JdbcApprovalService service =
                new JdbcApprovalService(
                        jdbc,
                        clock,
                        new ObjectMapper(),
                        proposalExpiry,
                        org.mockito.Mockito.mock(TicketAuthorityLock.class),
                        org.mockito.Mockito.mock(HumanHandoffService.class),
                        org.mockito.Mockito.mock(CustomerPublicProjectionAppender.class),
                        900,
                        900);

        service.queue("approver-demo");

        InOrder order = inOrder(clock, proposalExpiry, jdbc);
        order.verify(clock).instant();
        order.verify(proposalExpiry).expireDue(beforeWait);
        order.verify(clock).instant();
        order.verify(jdbc)
                .query(
                        contains("p.expires_at > ?"),
                        any(RowMapper.class),
                        eq(Timestamp.from(afterWait)),
                        eq(Timestamp.from(afterWait)),
                        eq("approver-demo"));
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        org.mockito.Mockito.verify(jdbc)
                .query(
                        sql.capture(),
                        any(RowMapper.class),
                        eq(Timestamp.from(afterWait)),
                        eq(Timestamp.from(afterWait)),
                        eq("approver-demo"));
        org.assertj.core.api.Assertions.assertThat(sql.getValue())
                .contains("p.expires_at > ?")
                .contains("l.expires_at > ?")
                .contains("compensation_proposal_revision_support_participant")
                .contains("participant.support_id = ?");
    }
}
