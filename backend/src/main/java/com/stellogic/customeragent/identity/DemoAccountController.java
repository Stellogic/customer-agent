package com.stellogic.customeragent.identity;

import com.stellogic.customeragent.identity.HumanIdentityDirectory.SubjectType;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("local-demo")
@RequestMapping("/api/auth/demo-accounts")
public final class DemoAccountController {
    @GetMapping
    public List<DemoAccount> accounts() {
        return LocalDemoHumanAccountsConfiguration.accounts().stream()
                .map(
                        account ->
                                new DemoAccount(
                                        account.username(),
                                        account.displayName(),
                                        account.subjectType(),
                                        LocalDemoHumanAccountsConfiguration.DEMO_PASSWORD))
                .toList();
    }

    public record DemoAccount(
            String username, String displayName, SubjectType subjectType, String password) {}
}
