package com.stellogic.customeragent.investigation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockingDetails;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.sla.SlaService;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
import com.stellogic.customeragent.ticket.TicketResolutionTransition;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.web.server.ResponseStatusException;

class JdbcAgentInvestigationServiceAuthorizationTest {
    @Test
    @SuppressWarnings("unchecked")
    void siblingSummaryRejectsAmbiguousAliasesAndCapsTheProjection() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenAnswer(
                        invocation -> {
                            String sql = invocation.getArgument(0, String.class);
                            return sql.startsWith("select t.order_reference")
                                    ? List.of("ORDER-DELAY-AMBIGUOUS")
                                    : List.of();
                        });
        JdbcAgentInvestigationService service =
                new JdbcAgentInvestigationService(
                        jdbc,
                        mock(AgentAccessAudit.class),
                        Clock.fixed(Instant.parse("2026-08-25T00:00:00Z"), ZoneOffset.UTC),
                        mock(JdbcCompensationProposalStore.class),
                        mock(SlaService.class),
                        mock(TicketAuthorityLock.class),
                        mock(CustomerPublicProjectionAppender.class),
                        mock(TicketResolutionTransition.class));

        assertThat(service.siblingTicketSummary(UUID.randomUUID(), UUID.randomUUID()).tickets())
                .isEmpty();

        String summarySql =
                mockingDetails(jdbc).getInvocations().stream()
                        .map(invocation -> invocation.getArgument(0, String.class))
                        .filter(sql -> sql.contains("from support_ticket current_ticket"))
                        .findFirst()
                        .orElseThrow();
        assertThat(summarySql)
                .contains("count(distinct alias.order_reference)")
                .contains("= 1")
                .contains("limit 20");
    }

    @Test
    @SuppressWarnings("unchecked")
    void staleHumanPreferredOrNonInvestigatingResultsCannotPublishAMessage() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.query(anyString(), any(ResultSetExtractor.class), any(Object[].class)))
                .thenReturn(null);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of());
        CustomerPublicProjectionAppender publicProjection =
                mock(CustomerPublicProjectionAppender.class);
        JdbcAgentInvestigationService service =
                new JdbcAgentInvestigationService(
                        jdbc,
                        mock(AgentAccessAudit.class),
                        Clock.fixed(Instant.parse("2026-08-25T00:00:00Z"), ZoneOffset.UTC),
                        mock(JdbcCompensationProposalStore.class),
                        mock(SlaService.class),
                        mock(TicketAuthorityLock.class),
                        publicProjection,
                        mock(TicketResolutionTransition.class));

        assertThatThrownBy(
                        () ->
                                service.submit(
                                        UUID.randomUUID(),
                                        UUID.randomUUID(),
                                        "late-customer-reply",
                                        safeConclusion()))
                .isInstanceOf(ResponseStatusException.class);

        String authorizationSql =
                mockingDetails(jdbc).getInvocations().stream()
                        .map(invocation -> invocation.getArgument(0, String.class))
                        .filter(sql -> sql.contains("from agent_processing_generation g"))
                        .findFirst()
                        .orElseThrow();
        assertThat(authorizationSql)
                .contains("g.status = 'ACTIVE'")
                .contains("t.handling_mode = 'AGENT'")
                .contains("t.lifecycle_state = 'INVESTIGATING'")
                .contains("not t.customer_human_preference")
                .contains("max(current_generation.generation_number)");
        verifyNoInteractions(publicProjection);
    }

    private static InvestigationConclusion safeConclusion() {
        List<String> evidence = List.of("order:ORDER-122", "logistics:ORDER-122");
        return new InvestigationConclusion(
                true,
                DecisionReasonCode.LOGISTICS_DELAY,
                80,
                288000,
                "ORDER-122",
                evidence,
                new CustomerReplyEnvelope(
                        "customer-reply-v1",
                        "订单 ORDER-122 的调查已完成，补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
                        CustomerReplyIntent.COMPENSATION_REVIEW_PENDING,
                        evidence,
                        false,
                        "ORDER-122"));
    }
}
