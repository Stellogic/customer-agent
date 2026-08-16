package com.stellogic.customeragent.identity;

import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanCapability;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.HumanRole;
import com.stellogic.customeragent.identity.HumanIdentityDirectory.SubjectType;
import java.util.List;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;

@Configuration(proxyBeanMethods = false)
@Profile("local-demo")
public class LocalDemoHumanAccountsConfiguration {
    static final String DEMO_PASSWORD = "local-demo-password";
    private static final List<DemoHumanAccount> ACCOUNTS =
            List.of(
                    new DemoHumanAccount(
                            "customer-demo",
                            "演示客户",
                            SubjectType.CUSTOMER,
                            List.of(HumanRole.CUSTOMER),
                            List.of(HumanCapability.CUSTOMER_HELP_ACCESS)),
                    new DemoHumanAccount(
                            "support-demo",
                            "演示客服",
                            SubjectType.INTERNAL,
                            List.of(HumanRole.SUPPORT),
                            List.of(HumanCapability.SUPPORT_WORKBENCH_ACCESS)),
                    new DemoHumanAccount(
                            "approver-demo",
                            "演示审批人",
                            SubjectType.INTERNAL,
                            List.of(HumanRole.APPROVER),
                            List.of(HumanCapability.APPROVAL_WORKBENCH_ACCESS)),
                    new DemoHumanAccount(
                            "internal-demo",
                            "演示双角色工作人员",
                            SubjectType.INTERNAL,
                            List.of(HumanRole.SUPPORT, HumanRole.APPROVER),
                            List.of(
                                    HumanCapability.SUPPORT_WORKBENCH_ACCESS,
                                    HumanCapability.APPROVAL_WORKBENCH_ACCESS)));

    @Bean
    UserDetailsService localDemoHumanUsers(
            org.springframework.security.crypto.password.PasswordEncoder passwordEncoder) {
        String password = passwordEncoder.encode(DEMO_PASSWORD);
        UserDetails[] users =
                ACCOUNTS.stream()
                        .map(
                                account ->
                                        User.withUsername(account.username())
                                                .password(password)
                                                .roles(
                                                        account.roles().stream()
                                                                .map(Enum::name)
                                                                .toArray(String[]::new))
                                                .build())
                        .toArray(UserDetails[]::new);
        return new InMemoryUserDetailsManager(users);
    }

    @Bean
    HumanIdentityDirectory localDemoHumanIdentities() {
        return new HumanIdentityDirectory(
                ACCOUNTS.stream()
                        .map(
                                account ->
                                        new HumanIdentityDirectory.HumanIdentity(
                                                account.username(),
                                                account.displayName(),
                                                account.subjectType(),
                                                account.roles(),
                                                account.capabilities()))
                        .toList());
    }

    static List<DemoHumanAccount> accounts() {
        return ACCOUNTS;
    }

    record DemoHumanAccount(
            String username,
            String displayName,
            SubjectType subjectType,
            List<HumanRole> roles,
            List<HumanCapability> capabilities) {
        DemoHumanAccount {
            roles = List.copyOf(roles);
            capabilities = List.copyOf(capabilities);
        }
    }
}
