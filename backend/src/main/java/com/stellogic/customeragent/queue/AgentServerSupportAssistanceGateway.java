package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import java.time.Duration;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
final class AgentServerSupportAssistanceGateway implements SupportAssistanceGateway {
    private final RestClient agent;
    private final ObjectMapper json;

    AgentServerSupportAssistanceGateway(@Value("${baseline.agent.base-url}") String baseUrl,
            @Value("${baseline.agent.token}") String token, ObjectMapper json) {
        this.json = json;
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(3));
        factory.setReadTimeout(Duration.ofSeconds(30));
        agent = RestClient.builder().baseUrl(baseUrl).defaultHeader("Authorization", "Bearer " + token)
                .requestFactory(factory).build();
    }

    @Override
    public JsonNode generate(SupportAssistanceKind kind, String query,
            SupportAssistanceContext.Snapshot context, AgentKnowledgeResult knowledge) {
        String response = agent.post().uri("/runs/wait").contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("assistant_id", "support_assistance", "input", Map.of(
                        "requested_by", "spring", "kind", kind.name(), "query", query,
                        "context", Map.of("description", context.description(),
                                "messages", context.messages(), "facts", context.facts()),
                        "knowledge", knowledge)))
                .retrieve().body(String.class);
        return json.readTree(response).path("support_assistance");
    }
}
