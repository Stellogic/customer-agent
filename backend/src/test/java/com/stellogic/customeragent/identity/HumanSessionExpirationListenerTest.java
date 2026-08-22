package com.stellogic.customeragent.identity;

import static org.assertj.core.api.Assertions.assertThat;

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

@ExtendWith(OutputCaptureExtension.class)
class HumanSessionExpirationListenerTest {
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
