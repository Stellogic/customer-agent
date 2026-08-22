package com.stellogic.customeragent.identity;

import java.util.List;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;

public final class HumanTestPrincipals {
    private HumanTestPrincipals() {}

    public static UsernamePasswordAuthenticationToken support() {
        return UsernamePasswordAuthenticationToken.authenticated("support-demo", "n/a", List.of());
    }

    public static UsernamePasswordAuthenticationToken approver() {
        return UsernamePasswordAuthenticationToken.authenticated("approver-demo", "n/a", List.of());
    }
}
