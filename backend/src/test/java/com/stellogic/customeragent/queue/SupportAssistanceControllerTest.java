package com.stellogic.customeragent.queue;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static com.stellogic.customeragent.identity.HumanTestPrincipals.support;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

class SupportAssistanceControllerTest {
    private final SupportAssistanceContext context = mock(SupportAssistanceContext.class);
    private final SupportAssistanceService service = mock(SupportAssistanceService.class);
    private final SupportAssistanceController controller = new SupportAssistanceController(context, service);
    private final UUID ticket = UUID.randomUUID();
    private final UUID requestId = UUID.randomUUID();

    @Test
    void logoutDuringGenerationRejectsContentEvenWhenAssignmentRemainsActive() {
        var http = new MockHttpServletRequest();
        var session = session("support-demo");
        http.setSession(session);
        when(service.request(eq("support-demo"), eq(ticket), any())).thenAnswer(invocation -> {
            session.invalidate();
            return new ObjectMapper().readTree("{\"view\":{\"status\":\"ready\",\"text\":\"内部结果\"}}");
        });
        var failure = assertThrows(ResponseStatusException.class, () -> controller.request(support(), ticket,
                Map.of("schema", "support-assistance-v1", "assignmentId", UUID.randomUUID().toString(),
                        "requestId", requestId.toString(), "kind", "draft", "query", "合成查询"), http));
        assertEquals(HttpStatus.UNAUTHORIZED, failure.getStatusCode());
    }

    @Test
    void subjectChangeDuringReceiptReadRejectsOldSubjectsResult() {
        var http = new MockHttpServletRequest();
        var session = session("support-demo");
        http.setSession(session);
        when(service.result("support-demo", ticket, requestId)).thenAnswer(invocation -> {
            var security = (SecurityContext) session.getAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY);
            security.setAuthentication(UsernamePasswordAuthenticationToken.authenticated("support-other", "n/a", java.util.List.of()));
            return new ObjectMapper().createObjectNode();
        });
        var failure = assertThrows(ResponseStatusException.class,
                () -> controller.result(support(), ticket, requestId, http));
        assertEquals(HttpStatus.UNAUTHORIZED, failure.getStatusCode());
    }
}
