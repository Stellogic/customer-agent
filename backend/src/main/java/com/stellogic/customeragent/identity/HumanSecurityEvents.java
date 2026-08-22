package com.stellogic.customeragent.identity;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

final class HumanSecurityEvents {
    static final String EXPLICIT_LOGOUT_ATTRIBUTE =
            HumanSecurityEvents.class.getName() + ".explicitLogout";

    private static final Logger SECURITY_LOG = LoggerFactory.getLogger("security.human-session");

    void loginSucceeded(String subjectId) {
        SECURITY_LOG.info("security_event=human_login outcome=success subject_id={}", subjectId);
    }

    void loginFailed() {
        SECURITY_LOG.info("security_event=human_login outcome=failure subject_id=unresolved");
    }

    void loggedOut(String subjectId) {
        SECURITY_LOG.info("security_event=human_logout outcome=success subject_id={}", subjectId);
    }

    void sessionExpired(String subjectId) {
        SECURITY_LOG.info("security_event=human_session outcome=expired subject_id={}", subjectId);
    }
}
