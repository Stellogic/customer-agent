package com.stellogic.customeragent.ticket;

import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class AgentReplyStreamControllerTest {
    private static final UUID TICKET_ID = UUID.fromString("15900000-0000-0000-0000-000000000001");
    private static final UUID GENERATION_ID =
            UUID.fromString("15900000-0000-0000-0000-000000000002");
    private AgentReplyStreamService service;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        service = org.mockito.Mockito.mock(AgentReplyStreamService.class);
        mvc =
                MockMvcBuilders.standaloneSetup(
                                new AgentReplyStreamController(service, "agent-secret"))
                        .build();
    }

    @Test
    void acceptsARealContentDeltaThroughTheGenerationScopedMachineBoundary() throws Exception {
        org.mockito.Mockito.when(
                        service.append(
                                new AgentReplyStreamCommand(
                                        TICKET_ID,
                                        GENERATION_ID,
                                        "stream-159-delta-1",
                                        AgentReplyStreamEventType.CONTENT_DELTA,
                                        0,
                                        "正在核对物流记录",
                                        null)))
                .thenReturn(new AgentReplyStreamResult(false));
        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/public-reply-events",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .header("Authorization", "Bearer agent-secret")
                                .header("X-Agent-Generation-Id", GENERATION_ID)
                                .header("X-Agent-Operation", "PUBLISH_PUBLIC_REPLY_EVENT")
                                .header("Idempotency-Key", "stream-159-delta-1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "type":"CONTENT_DELTA",
                                          "chunkIndex":0,
                                          "delta":"正在核对物流记录"
                                        }
                                        """))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.accepted").value(true))
                .andExpect(jsonPath("$.replayed").value(false));

        verify(service)
                .append(
                        new AgentReplyStreamCommand(
                                TICKET_ID,
                                GENERATION_ID,
                                "stream-159-delta-1",
                                AgentReplyStreamEventType.CONTENT_DELTA,
                                0,
                                "正在核对物流记录",
                                null));
    }

    @Test
    void preservesWhitespaceOnlyContentDelta() throws Exception {
        org.mockito.Mockito.when(service.append(org.mockito.ArgumentMatchers.any()))
                .thenReturn(new AgentReplyStreamResult(false));
        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/public-reply-events",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .header("Authorization", "Bearer agent-secret")
                                .header("X-Agent-Generation-Id", GENERATION_ID)
                                .header("X-Agent-Operation", "PUBLISH_PUBLIC_REPLY_EVENT")
                                .header("Idempotency-Key", "stream-whitespace")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"type\":\"CONTENT_DELTA\",\"chunkIndex\":1,\"delta\":\" \"}"))
                .andExpect(status().isAccepted());
        verify(service)
                .append(
                        new AgentReplyStreamCommand(
                                TICKET_ID,
                                GENERATION_ID,
                                "stream-whitespace",
                                AgentReplyStreamEventType.CONTENT_DELTA,
                                1,
                                " ",
                                null));
    }

    @Test
    void rejectsInternalFieldsBeforeTheyReachTheProductEventLog() throws Exception {
        mvc.perform(
                        post(
                                        "/internal/agent/tickets/{ticketId}/generations/{generationId}/public-reply-events",
                                        TICKET_ID,
                                        GENERATION_ID)
                                .header("Authorization", "Bearer agent-secret")
                                .header("X-Agent-Generation-Id", GENERATION_ID)
                                .header("X-Agent-Operation", "PUBLISH_PUBLIC_REPLY_EVENT")
                                .header("Idempotency-Key", "stream-159-secret")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "type":"PROGRESS",
                                          "stage":"VERIFYING_FACTS",
                                          "reasoning":"secret"
                                        }
                                        """))
                .andExpect(status().isBadRequest());
    }
}
