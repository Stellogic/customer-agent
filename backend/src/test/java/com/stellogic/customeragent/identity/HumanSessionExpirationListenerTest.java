package com.stellogic.customeragent.identity;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.stellogic.customeragent.stream.AuthorizedSsePollingStream;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSessionEvent;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@ExtendWith(OutputCaptureExtension.class)
class HumanSessionExpirationListenerTest {
    @Test
    void sessionFixationRevokesStreamsBoundBeforeTheSubjectReplacement() {
        MockHttpSession session = new MockHttpSession();
        HttpServletRequest request = org.mockito.Mockito.mock(HttpServletRequest.class);
        org.mockito.Mockito.when(request.getSession(false)).thenReturn(session);
        var source =
                AuthorizedSsePollingStream.requireCurrentHttpSession(
                        request,
                        null,
                        new AuthorizedSsePollingStream.Source<String>() {
                            @Override
                            public List<String> events(String afterCursor) {
                                return List.of();
                            }

                            @Override
                            public void authorize() {}

                            @Override
                            public String cursor(String event) {
                                return event;
                            }

                            @Override
                            public SseEmitter.SseEventBuilder render(String event) {
                                return SseEmitter.event().data(event);
                            }
                        });

        new HumanSessionExpirationListener(new HumanSecurityEvents())
                .sessionIdChanged(new HttpSessionEvent(session), "old-session-id");

        assertThatThrownBy(source::authorize).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void inactivityExpirationLogsOnlyTheSubjectAndControlledEventFields(CapturedOutput output) {
        MockHttpSession session = new MockHttpSession();
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(
                        "support-demo", "credential-must-not-be-logged", List.of()));
        session.setAttribute(
                HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, context);

        new HumanSessionExpirationListener(new HumanSecurityEvents())
                .sessionDestroyed(new HttpSessionEvent(session));

        assertThat(output)
                .contains("security_event=human_session outcome=expired subject_id=support-demo")
                .doesNotContain("credential-must-not-be-logged");
    }
}
