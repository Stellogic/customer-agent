package com.stellogic.customeragent.identity;

import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanCapability;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanRole;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.SubjectType;
import java.util.List;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public final class AuthSessionController {
    private final HumanIdentityDirectory identities;

    public AuthSessionController(HumanIdentityDirectory identities) {
        this.identities = identities;
    }

    @GetMapping("/csrf")
    public CsrfResponse csrf(CsrfToken csrfToken) {
        return new CsrfResponse(csrfToken.getToken(), csrfToken.getHeaderName());
    }

    @GetMapping("/session")
    public CurrentHumanSession session(Authentication authentication) {
        HumanIdentityDirectory.HumanIdentity principal =
                identities.require(authentication.getName());
        return new CurrentHumanSession(
                principal.id(),
                principal.displayName(),
                principal.subjectType(),
                principal.roles(),
                principal.capabilities());
    }

    public record CsrfResponse(String token, String headerName) {}

    public record CurrentHumanSession(
            String id,
            String displayName,
            SubjectType subjectType,
            List<HumanRole> roles,
            List<HumanCapability> capabilities) {}
}
