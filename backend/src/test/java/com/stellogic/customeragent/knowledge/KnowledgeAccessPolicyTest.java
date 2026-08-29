package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.stellogic.customeragent.identity.HumanIdentityDirectory;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanCapability;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanIdentity;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanRole;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.SubjectType;
import java.util.List;
import org.junit.jupiter.api.Test;

class KnowledgeAccessPolicyTest {
    @Test
    void supportAndApproverReceiveCapabilityBackedScopes() {
        KnowledgeAccessPolicy policy =
                new KnowledgeAccessPolicy(
                        directory(
                                identity(
                                        "support-demo",
                                        SubjectType.INTERNAL,
                                        List.of(HumanRole.SUPPORT),
                                        List.of(
                                                HumanCapability.SUPPORT_WORKBENCH_ACCESS,
                                                HumanCapability.KNOWLEDGE_READ_ACCESS)),
                                identity(
                                        "approver-demo",
                                        SubjectType.INTERNAL,
                                        List.of(HumanRole.APPROVER),
                                        List.of(
                                                HumanCapability.APPROVAL_WORKBENCH_ACCESS,
                                                HumanCapability.KNOWLEDGE_READ_ACCESS))));

        assertThat(policy.requireScopes("support-demo")).containsExactly("INTERNAL", "SUPPORT");
        assertThat(policy.requireScopes("approver-demo")).containsExactly("INTERNAL", "APPROVER");
    }

    @Test
    void customerAndInternalIdentityWithoutCapabilityAreDenied() {
        KnowledgeAccessPolicy policy =
                new KnowledgeAccessPolicy(
                        directory(
                                identity(
                                        "customer-demo",
                                        SubjectType.CUSTOMER,
                                        List.of(HumanRole.CUSTOMER),
                                        List.of(HumanCapability.CUSTOMER_HELP_ACCESS)),
                                identity(
                                        "support-without-knowledge",
                                        SubjectType.INTERNAL,
                                        List.of(HumanRole.SUPPORT),
                                        List.of(HumanCapability.SUPPORT_WORKBENCH_ACCESS))));

        assertThatThrownBy(() -> policy.requireScopes("customer-demo"))
                .isInstanceOf(KnowledgeAccessDeniedException.class);
        assertThatThrownBy(() -> policy.requireScopes("support-without-knowledge"))
                .isInstanceOf(KnowledgeAccessDeniedException.class);
    }

    private static HumanIdentityDirectory directory(HumanIdentity... identities) {
        return new HumanIdentityDirectory(List.of(identities));
    }

    private static HumanIdentity identity(
            String id,
            SubjectType subjectType,
            List<HumanRole> roles,
            List<HumanCapability> capabilities) {
        return new HumanIdentity(id, id, subjectType, roles, capabilities);
    }
}
