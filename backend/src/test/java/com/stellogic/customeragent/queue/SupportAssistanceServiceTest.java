package com.stellogic.customeragent.queue;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class SupportAssistanceServiceTest {
    private final UUID ticket = UUID.randomUUID();
    private final UUID assignment = UUID.randomUUID();
    private final UUID id = UUID.randomUUID();
    private final SupportAssistanceRequests requests = mock(SupportAssistanceRequests.class);
    private final SupportAssistanceContext context = mock(SupportAssistanceContext.class);
    private final AgentKnowledgeRetrievalAdapter knowledge = mock(AgentKnowledgeRetrievalAdapter.class);
    private final SupportAssistanceGateway gateway = mock(SupportAssistanceGateway.class);
    private final ObjectMapper json = new ObjectMapper();
    private final SupportAssistanceService service = new SupportAssistanceService(requests, context, knowledge, gateway, json);
    private final SupportAssistanceRequest request = new SupportAssistanceRequest(assignment, id, SupportAssistanceKind.draft, "合成查询");

    @Test
    void pendingReplayDoesNotRetrieveOrGenerateAgain() {
        var receipt = receipt(null, false);
        when(requests.begin("support-demo", ticket, request)).thenReturn(receipt);
        when(requests.read("support-demo", ticket, id)).thenReturn(receipt);
        assertEquals("loading", service.request("support-demo", ticket, request).path("view").path("status").asString());
        verify(knowledge, never()).searchSupport(anyString(), anyString());
        verify(gateway, never()).generate(any(), anyString(), any(), any());
    }

    @Test
    void revocationAfterRetrievalPreventsModelCall() {
        when(requests.begin("support-demo", ticket, request)).thenReturn(receipt(null, true));
        when(knowledge.searchSupport("support-demo", request.query()))
                .thenReturn(new AgentKnowledgeResult("agent-knowledge-v1", 1, List.of()));
        doThrow(new SupportTicketNotFoundException()).when(context).requireAssignment("support-demo", ticket, assignment);
        assertThrows(SupportTicketNotFoundException.class, () -> service.request("support-demo", ticket, request));
        verify(gateway, never()).generate(any(), anyString(), any(), any());
        verify(requests, never()).finish(anyString(), any(), any(), anyString(), eq(false));
    }

    @Test
    void storedAnswerIsRevalidatedButAuditAndKnowledgePayloadNeverReachBrowser() {
        var stored = json.createObjectNode();
        stored.set("knowledge", json.valueToTree(new AgentKnowledgeResult("agent-knowledge-v1", 1, List.of())));
        stored.set("view", json.readTree("{\"status\":\"insufficient\",\"explanation\":\"资料不足\"}"));
        stored.put("audit", "内部模型调用统计");
        when(requests.read("support-demo", ticket, id)).thenReturn(receipt(json.writeValueAsString(stored), false));
        var response = service.result("support-demo", ticket, id);
        verify(knowledge).revalidateSupport(eq("support-demo"), any());
        verify(context).requireAssignment("support-demo", ticket, assignment);
        assertEquals(false, response.has("audit"));
        assertEquals(false, response.has("knowledge"));
    }

    private SupportAssistanceReceipt receipt(String result, boolean execute) {
        return new SupportAssistanceReceipt(ticket, assignment, id, SupportAssistanceKind.draft,
                result == null ? "PENDING" : "COMPLETED", result, execute,
                new SupportAssistanceContext.Snapshot(ticket, assignment, "合成工单", List.of(), List.of()));
    }
}
