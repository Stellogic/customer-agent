package com.stellogic.customeragent.identity;

import java.util.List;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;

@Configuration(proxyBeanMethods = false)
@Profile("!local-demo")
public class ProductionHumanAccountsConfiguration {
    @Bean
    UserDetailsService productionHumanUsers() {
        return username -> {
            throw new UsernameNotFoundException("human identity source is not configured");
        };
    }

    @Bean
    HumanIdentityDirectory productionHumanIdentities() {
        return new HumanIdentityDirectory(List.of());
    }
}
