package com.stellogic.customeragent.identity;

import java.util.List;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;

public final class HumanTestPrincipals {
    private HumanTestPrincipals() {}

    public static UsernamePasswordAuthenticationToken support() {
        return UsernamePasswordAuthenticationToken.authenticated("support-demo", "n/a", List.of());
    }

    public static UsernamePasswordAuthenticationToken approver() {
        return UsernamePasswordAuthenticationToken.authenticated("approver-demo", "n/a", List.of());
    }

    public static MockHttpSession session(String subject) {
        MockHttpSession session = new MockHttpSession();
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(subject, "n/a", List.of()));
        session.setAttribute(
                HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, context);
        return session;
    }
}
