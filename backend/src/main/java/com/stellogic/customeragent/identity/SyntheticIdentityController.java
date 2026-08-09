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
        return List.of(
                new SyntheticIdentity("customer-demo", "CUSTOMER", "客户演示入口"),
                new SyntheticIdentity("customer-other-demo", "CUSTOMER", "另一客户授权边界入口"),
                new SyntheticIdentity("support-demo", "SUPPORT", "客服演示入口"),
                new SyntheticIdentity("approver-demo", "APPROVER", "审批人演示入口"),
                new SyntheticIdentity("approver-other-demo", "APPROVER", "另一审批人并发边界入口"),
                new SyntheticIdentity("agent-machine", "AGENT", "受限 Agent 机器身份"),
                new SyntheticIdentity("executor-machine", "COMPENSATION_EXECUTOR", "受限补偿执行器机器身份"));
    }

    public record SyntheticIdentity(String id, String role, String label) {}
}
