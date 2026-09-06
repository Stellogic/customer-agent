package com.stellogic.customeragent.investigation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import com.stellogic.customeragent.ticket.CustomerPublicProjectionAppender;
import java.time.Clock;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

class RequiredFactsCatalogTest {
    @ParameterizedTest
    @ValueSource(strings = {"LOGISTICS_DELAY", "DUPLICATE_CHARGE", "PACKAGE_NOT_RECEIVED"})
    @SuppressWarnings("unchecked")
    void authorizedCatalogExposesOnlyTheMigratedScenarioRequirements(String issueKind)
            throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class)))
                .thenReturn(List.of("ORDER-228"));
        when(jdbc.queryForObject(anyString(), any(Class.class), any(Object[].class)))
                .thenReturn(issueKind);
        ObjectMapper json = new ObjectMapper();
        JdbcAgentInvestigationService service =
                new JdbcAgentInvestigationService(
                        jdbc,
                        mock(AgentAccessAudit.class),
                        Clock.systemUTC(),
                        mock(JdbcCompensationProposalStore.class),
                        mock(TicketAuthorityLock.class),
                        mock(CustomerPublicProjectionAppender.class),
                        json,
                        mock(AgentKnowledgeRetrievalAdapter.class));
        UUID ticketId = UUID.randomUUID();
        UUID generationId = UUID.randomUUID();
        String response =
                MockMvcBuilders.standaloneSetup(
                                new AgentInvestigationController(
                                        service,
                                        "agent-token",
                                        mock(AgentKnowledgeRetrievalAdapter.class)))
                        .build()
                        .perform(
                                get(
                                                "/internal/agent/tickets/{ticketId}/generations/{generationId}/capabilities",
                                                ticketId,
                                                generationId)
                                        .header("Authorization", "Bearer agent-token")
                                        .header("X-Agent-Generation-Id", generationId)
                                        .header(
                                                "X-Agent-Operation",
                                                "USE_INVESTIGATION_CAPABILITY"))
                        .andExpect(status().isOk())
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        JsonNode catalog = json.readTree(response);
        assertThat(catalog.has("requiredFacts")).isTrue();
        JsonNode requirements = catalog.get("requiredFacts");
        if (issueKind.equals("PACKAGE_NOT_RECEIVED")) {
            assertThat(requirements.isNull()).isTrue();
            return;
        }
        assertThat(requirements.path("policyVersion").asText())
                .isEqualTo(EvidenceSufficiencyPolicy.VERSION);
        assertThat(requirements.path("riskScenario").asText()).isEqualTo(issueKind);
        Map<String, List<Object>> mappings = new HashMap<>();
        for (JsonNode fact : requirements.path("facts")) {
            mappings.put(
                    fact.path("factType").asText(),
                    List.of(
                            fact.path("capability").asText(),
                            fact.path("resultField").asText(),
                            fact.path("evidenceIndex").asInt(),
                            fact.path("applicability").asText()));
        }
        if (issueKind.equals("DUPLICATE_CHARGE")) {
            assertThat(mappings)
                    .containsExactlyInAnyOrderEntriesOf(
                            Map.of(
                                    "ORDER",
                                            List.of(
                                                    "CONFIRM_ORDER",
                                                    "orderReference",
                                                    0,
                                                    "ORDER_IDENTITY"),
                                    "PAYMENT",
                                            List.of(
                                                    "READ_PAYMENT_AND_REFUNDS",
                                                    "paid",
                                                    0,
                                                    "PAYMENT_STATUS"),
                                    "ORDER_CANCELLATION",
                                            List.of(
                                                    "READ_PAYMENT_AND_REFUNDS",
                                                    "cancelled",
                                                    0,
                                                    "ORDER_ELIGIBILITY"),
                                    "REFUND_STATUS",
                                            List.of(
                                                    "READ_PAYMENT_AND_REFUNDS",
                                                    "fullyRefunded",
                                                    0,
                                                    "REFUND_STATUS"),
                                    "EXISTING_COMPENSATION",
                                            List.of(
                                                    "READ_COMPENSATION_AND_PENDING_ACTIONS",
                                                    "existingCompensation",
                                                    0,
                                                    "EXISTING_COMPENSATION"),
                                    "PENDING_ACTION_COUNT",
                                            List.of(
                                                    "READ_COMPENSATION_AND_PENDING_ACTIONS",
                                                    "pendingActionCount",
                                                    1,
                                                    "PENDING_ACTIONS")));
            return;
        }
        assertThat(mappings)
                .containsExactlyInAnyOrderEntriesOf(
                        Map.of(
                                "ORDER",
                                        List.of(
                                                "CONFIRM_ORDER",
                                                "orderReference",
                                                0,
                                                "ORDER_IDENTITY"),
                                "LOGISTICS_DELAY_HOURS",
                                        List.of(
                                                "READ_LOGISTICS",
                                                "delayHours",
                                                0,
                                                "DELAY_DURATION"),
                                "LOGISTICS_DELAY_SECONDS",
                                        List.of(
                                                "READ_LOGISTICS",
                                                "delaySeconds",
                                                0,
                                                "DELAY_DURATION"),
                                "PAYMENT",
                                        List.of(
                                                "READ_PAYMENT_AND_REFUNDS",
                                                "paid",
                                                0,
                                                "ORDER_ELIGIBILITY"),
                                "ORDER_CANCELLATION",
                                        List.of(
                                                "READ_PAYMENT_AND_REFUNDS",
                                                "cancelled",
                                                0,
                                                "ORDER_ELIGIBILITY"),
                                "REFUND_STATUS",
                                        List.of(
                                                "READ_PAYMENT_AND_REFUNDS",
                                                "fullyRefunded",
                                                0,
                                                "ORDER_ELIGIBILITY"),
                                "EXISTING_COMPENSATION",
                                        List.of(
                                                "READ_COMPENSATION_AND_PENDING_ACTIONS",
                                                "existingCompensation",
                                                0,
                                                "EXISTING_COMPENSATION"),
                                "PENDING_ACTION_COUNT",
                                        List.of(
                                                "READ_COMPENSATION_AND_PENDING_ACTIONS",
                                                "pendingActionCount",
                                                1,
                                                "PENDING_ACTIONS"),
                                "POLICY",
                                        List.of(
                                                "READ_APPLICABLE_POLICY",
                                                "policyVersion",
                                                0,
                                                "POLICY_BASIS")));
    }
}
