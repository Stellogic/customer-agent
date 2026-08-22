package com.stellogic.customeragent.identity;

import jakarta.servlet.http.HttpSessionEvent;
import jakarta.servlet.http.HttpSessionListener;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;

final class HumanSessionExpirationListener implements HttpSessionListener {
    private final HumanSecurityEvents securityEvents;

    HumanSessionExpirationListener(HumanSecurityEvents securityEvents) {
        this.securityEvents = securityEvents;
    }

    @Override
    public void sessionDestroyed(HttpSessionEvent event) {
        if (Boolean.TRUE.equals(
                event.getSession().getAttribute(HumanSecurityEvents.EXPLICIT_LOGOUT_ATTRIBUTE))) {
            return;
        }
        Object value =
                event.getSession()
                        .getAttribute(
                                HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY);
        if (value instanceof SecurityContext context && context.getAuthentication() != null) {
            securityEvents.sessionExpired(context.getAuthentication().getName());
        }
    }
}
