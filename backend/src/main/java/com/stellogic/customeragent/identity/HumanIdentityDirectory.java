package com.stellogic.customeragent.identity;

import java.util.List;
import java.util.Map;

public final class HumanIdentityDirectory {
    private final Map<String, HumanIdentity> identities;

    public HumanIdentityDirectory(List<HumanIdentity> identities) {
        this.identities =
                identities.stream()
                        .collect(
                                java.util.stream.Collectors.toUnmodifiableMap(
                                        HumanIdentity::id, i -> i));
    }

    public HumanIdentity require(String id) {
        HumanIdentity identity = identities.get(id);
        if (identity == null) {
            throw new IllegalStateException("authenticated human identity is not configured");
        }
        return identity;
    }

    public record HumanIdentity(
            String id,
            String displayName,
            SubjectType subjectType,
            List<HumanRole> roles,
            List<HumanCapability> capabilities) {
        public HumanIdentity {
            roles = List.copyOf(roles);
            capabilities = List.copyOf(capabilities);
        }
    }

    public enum SubjectType {
        CUSTOMER,
        INTERNAL
    }

    public enum HumanRole {
        CUSTOMER,
        SUPPORT,
        APPROVER
    }

    public enum HumanCapability {
        CUSTOMER_HELP_ACCESS,
        SUPPORT_WORKBENCH_ACCESS,
        APPROVAL_WORKBENCH_ACCESS
    }
}
