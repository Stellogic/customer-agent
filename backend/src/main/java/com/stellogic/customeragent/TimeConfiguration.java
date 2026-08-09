package com.stellogic.customeragent;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
class TimeConfiguration {
    @Bean
    Clock applicationClock(@Value("${baseline.clock.fixed-instant:}") String fixedInstant) {
        return fixedInstant.isBlank()
                ? Clock.systemUTC()
                : Clock.fixed(Instant.parse(fixedInstant), ZoneOffset.UTC);
    }
}
