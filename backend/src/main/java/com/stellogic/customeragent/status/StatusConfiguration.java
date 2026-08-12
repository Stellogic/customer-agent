package com.stellogic.customeragent.status;

import java.time.Duration;
import javax.sql.DataSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestClient;

@Configuration
class StatusConfiguration {

    @Bean
    SystemStatusService systemStatusService(
            DataSource dataSource,
            @Value("${baseline.agent.base-url}") String agentBaseUrl,
            @Value("${baseline.agent.token}") String agentToken,
            @Value("${baseline.agent.probe-connect-timeout}") Duration agentConnectTimeout,
            @Value("${baseline.agent.probe-read-timeout}") Duration agentReadTimeout) {
        JdbcTemplate jdbc = new JdbcTemplate(dataSource);
        AvailabilityProbe databaseProbe = () -> jdbc.queryForObject("select 1", Integer.class) == 1;
        return new SystemStatusService(
                databaseProbe,
                agentProbe(agentBaseUrl, agentToken, agentConnectTimeout, agentReadTimeout));
    }

    static AvailabilityProbe agentProbe(
            String agentBaseUrl, String agentToken, Duration connectTimeout, Duration readTimeout) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(requirePositive(connectTimeout, "connect timeout"));
        requestFactory.setReadTimeout(requirePositive(readTimeout, "read timeout"));
        RestClient agent =
                RestClient.builder()
                        .baseUrl(agentBaseUrl)
                        .defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + agentToken)
                        .requestFactory(requestFactory)
                        .build();

        return () ->
                agent.post()
                        .uri("/threads/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{}")
                        .exchange(
                                (request, response) -> response.getStatusCode().is2xxSuccessful());
    }

    private static Duration requirePositive(Duration timeout, String name) {
        if (timeout.isZero() || timeout.isNegative()) {
            throw new IllegalArgumentException(name + " must be positive");
        }
        return timeout;
    }
}
