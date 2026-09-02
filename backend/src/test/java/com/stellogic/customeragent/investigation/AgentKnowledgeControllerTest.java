package com.stellogic.customeragent.investigation;

import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

class AgentKnowledgeControllerTest {
    private static final UUID TICKET = UUID.fromString("23000000-0000-0000-0000-000000000001");
    private static final UUID GENERATION = UUID.fromString("23000000-0000-0000-0000-000000000002");
    private static final String REQUEST = "customer-knowledge-request";
    private static final String QUERY = "签收后未收到包裹怎么办";
    private static final String PATH =
            "/internal/agent/tickets/{ticketId}/generations/{generationId}/knowledge/search";
    private final AgentInvestigationService service = mock(AgentInvestigationService.class);
    private final AgentKnowledgeRetrievalAdapter knowledge =
            mock(AgentKnowledgeRetrievalAdapter.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(
                            new AgentInvestigationController(service, "agent-token", knowledge))
                    .build();
    private final AgentKnowledgeResult receipt =
            new AgentKnowledgeResult("agent-knowledge-v1", 7, List.of());

    @Test
    void authorizesBeforeSearchAndRechecksBeforeAcceptingEvenAnEmptyReceipt() throws Exception {
        when(knowledge.searchCustomer(QUERY)).thenReturn(receipt);
        when(service.acceptKnowledgeSearch(TICKET, GENERATION, REQUEST, QUERY, receipt))
                .thenReturn(receipt);

        mvc.perform(
                        post(PATH, TICKET, GENERATION)
                                .headers(headers())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.schema").value("agent-knowledge-v1"))
                .andExpect(jsonPath("$.indexGeneration").value(7))
                .andExpect(jsonPath("$.results").isEmpty());

        var order = inOrder(service, knowledge);
        order.verify(service).authorizeKnowledgeSearch(TICKET, GENERATION, REQUEST, QUERY);
        order.verify(knowledge).searchCustomer(QUERY);
        order.verify(service).acceptKnowledgeSearch(TICKET, GENERATION, REQUEST, QUERY, receipt);
    }

    @Test
    void retryRevalidatesTheSavedReceiptWithoutAnotherRetrieval() throws Exception {
        when(service.authorizeKnowledgeSearch(TICKET, GENERATION, REQUEST, QUERY))
                .thenReturn(receipt);
        when(knowledge.revalidateCustomer(receipt)).thenReturn(receipt);
        when(service.acceptKnowledgeSearch(TICKET, GENERATION, REQUEST, QUERY, receipt))
                .thenReturn(receipt);

        mvc.perform(
                        post(PATH, TICKET, GENERATION)
                                .headers(headers())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body()))
                .andExpect(status().isOk());

        verify(knowledge).revalidateCustomer(receipt);
        verify(knowledge, never()).searchCustomer(QUERY);
    }

    @Test
    void deniedGenerationDoesNotCallRetrieval() throws Exception {
        when(service.authorizeKnowledgeSearch(TICKET, GENERATION, REQUEST, QUERY))
                .thenThrow(new ResponseStatusException(HttpStatus.FORBIDDEN));

        mvc.perform(
                        post(PATH, TICKET, GENERATION)
                                .headers(headers())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body()))
                .andExpect(status().isForbidden());
        verifyNoInteractions(knowledge);
    }

    @Test
    void generationRevokedDuringSearchCannotReturnTheReceipt() throws Exception {
        when(knowledge.searchCustomer(QUERY)).thenReturn(receipt);
        doThrow(new ResponseStatusException(HttpStatus.FORBIDDEN))
                .when(service)
                .acceptKnowledgeSearch(TICKET, GENERATION, REQUEST, QUERY, receipt);

        mvc.perform(
                        post(PATH, TICKET, GENERATION)
                                .headers(headers())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body()))
                .andExpect(status().isForbidden());
    }

    @Test
    void requestCannotChooseItsOwnScope() throws Exception {
        mvc.perform(
                        post(PATH, TICKET, GENERATION)
                                .headers(headers())
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"query\":\"签收问题\",\"scope\":\"INTERNAL\"}"))
                .andExpect(status().isBadRequest());
        verifyNoInteractions(service, knowledge);
    }

    @Test
    void machineOperationScopeIsRequired() throws Exception {
        HttpHeaders headers = headers();
        headers.set("X-Agent-Operation", "USE_INVESTIGATION_CAPABILITY");
        mvc.perform(
                        post(PATH, TICKET, GENERATION)
                                .headers(headers)
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(body()))
                .andExpect(status().isForbidden());
        verifyNoInteractions(knowledge);
    }

    private static String body() {
        return "{\"query\":\"" + QUERY + "\"}";
    }

    private static HttpHeaders headers() {
        HttpHeaders headers = new HttpHeaders();
        headers.setBearerAuth("agent-token");
        headers.set("X-Agent-Generation-Id", GENERATION.toString());
        headers.set("X-Agent-Operation", "SEARCH_KNOWLEDGE");
        headers.set("Idempotency-Key", REQUEST);
        return headers;
    }
}
