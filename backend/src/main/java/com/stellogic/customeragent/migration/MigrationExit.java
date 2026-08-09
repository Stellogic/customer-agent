package com.stellogic.customeragent.migration;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "baseline.migrate-only", havingValue = "true")
public final class MigrationExit implements ApplicationRunner {
    private final ConfigurableApplicationContext context;

    public MigrationExit(ConfigurableApplicationContext context) {
        this.context = context;
    }

    @Override
    public void run(ApplicationArguments args) {
        context.close();
    }
}

