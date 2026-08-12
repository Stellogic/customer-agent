package com.stellogic.customeragent.status;

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
            @Value("${baseline.agent.token}") String agentToken) {
        JdbcTemplate jdbc = new JdbcTemplate(dataSource);
        RestClient agent =
                RestClient.builder()
                        .baseUrl(agentBaseUrl)
                        .defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + agentToken)
                        .requestFactory(new SimpleClientHttpRequestFactory())
                        .build();

        AvailabilityProbe databaseProbe = () -> jdbc.queryForObject("select 1", Integer.class) == 1;
        AvailabilityProbe agentProbe =
                () ->
                        agent.post()
                                .uri("/threads/search")
                                .contentType(MediaType.APPLICATION_JSON)
                                .body("{}")
                                .exchange(
                                        (request, response) ->
                                                response.getStatusCode().is2xxSuccessful());
        return new SystemStatusService(databaseProbe, agentProbe);
    }
}
