package com.stellogic.customeragent.identity;

import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("local-demo")
@RequestMapping("/api/demo")
public final class SyntheticIdentityController {

    @GetMapping("/identities")
    public List<SyntheticIdentity> identities() {
        List<SyntheticIdentity> identities = new java.util.ArrayList<>(List.of(
                new SyntheticIdentity("customer-demo", "CUSTOMER", "客户演示入口"),
                new SyntheticIdentity("customer-other-demo", "CUSTOMER", "另一客户授权边界入口"),
                new SyntheticIdentity("support-demo", "SUPPORT", "客服演示入口"),
                new SyntheticIdentity("agent-machine", "AGENT", "受限 Agent 机器身份"),
                new SyntheticIdentity("executor-machine", "COMPENSATION_EXECUTOR", "受限补偿执行器机器身份")));
        SyntheticApprovers.entries().stream()
                .map(entry -> new SyntheticIdentity(entry.id(), "APPROVER", entry.label()))
                .forEach(identities::add);
        return List.copyOf(identities);
    }

    public record SyntheticIdentity(String id, String role, String label) {}
}
