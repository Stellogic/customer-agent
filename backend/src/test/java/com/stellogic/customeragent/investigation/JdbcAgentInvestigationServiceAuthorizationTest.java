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
import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
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
import tools.jackson.databind.ObjectMapper;

class JdbcAgentInvestigationServiceAuthorizationTest {
    @Test
    @SuppressWarnings("unchecked")
    void concurrentWinnerCannotReplaceTheReceiptThatWasActuallyValidated() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        AgentKnowledgeResult previous = new AgentKnowledgeResult("agent-knowledge-v1", 7, List.of());
        AgentKnowledgeResult validated = new AgentKnowledgeResult("agent-knowledge-v1", 8, List.of());
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenAnswer(invocation -> invocation.getArgument(0, String.class).startsWith("select t.order_reference")
                        ? List.of("ORDER-169") : List.of(previous));
        JdbcAgentInvestigationService service = new JdbcAgentInvestigationService(
                jdbc, mock(AgentAccessAudit.class), Clock.systemUTC(),
                mock(JdbcCompensationProposalStore.class), mock(TicketAuthorityLock.class),
                mock(CustomerPublicProjectionAppender.class), mock(ObjectMapper.class), mock(com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter.class));

        assertThatThrownBy(() -> service.acceptKnowledgeSearch(
                UUID.randomUUID(), UUID.randomUUID(), "same-request", "配送指引", validated))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> assertThat(error.getStatusCode().value()).isEqualTo(409));
    }

    @Test
    @SuppressWarnings("unchecked")
    void customerCommunicationContextKeepsTheCompleteOrderedConversation() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenAnswer(
                        invocation -> {
                            String sql = invocation.getArgument(0, String.class);
                            if (sql.startsWith("select t.order_reference"))
                                return List.of("ORDER-122");
                            if (sql.startsWith("select description")) return List.of("原始问题");
                            return List.of();
                        });
        JdbcAgentInvestigationService service =
                new JdbcAgentInvestigationService(
                        jdbc,
                        mock(AgentAccessAudit.class),
                        Clock.fixed(Instant.parse("2026-08-25T00:00:00Z"), ZoneOffset.UTC),
                        mock(JdbcCompensationProposalStore.class),
                        mock(TicketAuthorityLock.class),
                        mock(CustomerPublicProjectionAppender.class),
                        mock(ObjectMapper.class), mock(com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter.class));

        service.customerCommunicationContext(UUID.randomUUID(), UUID.randomUUID());

        String conversationSql =
                mockingDetails(jdbc).getInvocations().stream()
                        .map(invocation -> invocation.getArgument(0, String.class))
                        .filter(sql -> sql.contains("from public_message"))
                        .findFirst()
                        .orElseThrow();
        assertThat(conversationSql).contains("order by message_sequence").doesNotContain("limit");
    }

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
                        mock(TicketAuthorityLock.class),
                        mock(CustomerPublicProjectionAppender.class),
                        mock(ObjectMapper.class), mock(com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter.class));

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
                        mock(TicketAuthorityLock.class),
                        publicProjection,
                        mock(ObjectMapper.class), mock(com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter.class));

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
                new EvidenceSufficiencyClaim(
                        InvestigationRiskScenario.LOGISTICS_DELAY,
                        EvidenceSufficiencyPolicy.VERSION,
                        structuredEvidence("ORDER-122")),
                new CustomerReplyEnvelope(
                        "customer-reply-v1",
                        "订单 ORDER-122 的调查已完成，补偿建议正在等待人工审批；审批完成前不会执行补偿或退款。",
                        CustomerReplyIntent.COMPENSATION_REVIEW_PENDING,
                        evidence,
                        false,
                        "ORDER-122"));
    }

    private static List<ConclusionEvidence> structuredEvidence(String orderReference) {
        return List.of(
                new ConclusionEvidence(
                        "order:" + orderReference, List.of(EvidenceApplicability.ORDER_IDENTITY)),
                new ConclusionEvidence(
                        "logistics:" + orderReference,
                        List.of(EvidenceApplicability.DELAY_DURATION)),
                new ConclusionEvidence(
                        "payment:" + orderReference,
                        List.of(EvidenceApplicability.ORDER_ELIGIBILITY)),
                new ConclusionEvidence(
                        "compensation:" + orderReference,
                        List.of(EvidenceApplicability.EXISTING_COMPENSATION)),
                new ConclusionEvidence(
                        "order-actions:" + orderReference,
                        List.of(EvidenceApplicability.PENDING_ACTIONS)),
                new ConclusionEvidence(
                        "policy:delay-policy-v1", List.of(EvidenceApplicability.POLICY_BASIS)));
    }
}
