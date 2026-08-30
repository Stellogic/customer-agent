package com.stellogic.customeragent.knowledge;

import com.stellogic.customeragent.identity.HumanIdentityDirectory;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanCapability;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanRole;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.SubjectType;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;

@Component
final class KnowledgeAccessPolicy {
    private final HumanIdentityDirectory identities;

    KnowledgeAccessPolicy(HumanIdentityDirectory identities) {
        this.identities = identities;
    }

    List<String> requireScopes(String principalId) {
        HumanIdentityDirectory.HumanIdentity identity = identities.require(principalId);
        if (identity.subjectType() != SubjectType.INTERNAL
                || !identity.capabilities().contains(HumanCapability.KNOWLEDGE_READ_ACCESS)) {
            throw new KnowledgeAccessDeniedException();
        }

        List<String> scopes = new ArrayList<>();
        scopes.add("INTERNAL");
        if (identity.roles().contains(HumanRole.SUPPORT)) scopes.add("SUPPORT");
        if (identity.roles().contains(HumanRole.APPROVER)) scopes.add("APPROVER");
        return List.copyOf(scopes);
    }
}
