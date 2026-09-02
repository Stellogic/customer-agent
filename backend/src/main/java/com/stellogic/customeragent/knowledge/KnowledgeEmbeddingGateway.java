package com.stellogic.customeragent.knowledge;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

@Component
final class KnowledgeEmbeddingGateway {
    static final String REVISION = "7999e1d3359715c523056ef9478215996d62a620";
    private final RestClient agent;
    private final ObjectMapper json;

    KnowledgeEmbeddingGateway(
            @Value("${baseline.agent.base-url}") String baseUrl,
            @Value("${baseline.agent.token}") String token,
            ObjectMapper json) {
        this.json = json;
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(3));
        factory.setReadTimeout(Duration.ofSeconds(60));
        agent =
                RestClient.builder()
                        .baseUrl(baseUrl)
                        .defaultHeader("Authorization", "Bearer " + token)
                        .requestFactory(factory)
                        .build();
    }

    List<String> encode(List<String> texts, boolean query) {
        try {
            String response =
                    agent.post()
                            .uri("/runs/wait")
                            .contentType(MediaType.APPLICATION_JSON)
                            .body(
                                    Map.of(
                                            "assistant_id",
                                            "knowledge_embedding",
                                            "input",
                                            Map.of(
                                                    "requested_by",
                                                    "spring",
                                                    "texts",
                                                    texts,
                                                    "kind",
                                                    query ? "QUERY" : "DOCUMENT")))
                            .retrieve()
                            .body(String.class);
            var value = json.readTree(response);
            var embeddings = value.path("embeddings");
            if (!REVISION.equals(value.path("revision").asText())
                    || !embeddings.isArray()
                    || embeddings.size() != texts.size()) {
                throw new KnowledgeRetrievalUnavailableException("MODEL_UNAVAILABLE");
            }
            List<String> vectors = new ArrayList<>();
            for (var vector : embeddings) {
                if (!vector.isArray() || vector.size() != 512) {
                    throw new KnowledgeRetrievalUnavailableException("MODEL_UNAVAILABLE");
                }
                double norm = 0;
                List<String> coordinates = new ArrayList<>();
                for (var coordinate : vector) {
                    double number = coordinate.asDouble();
                    if (!coordinate.isNumber() || !Double.isFinite(number)) {
                        throw new KnowledgeRetrievalUnavailableException("MODEL_UNAVAILABLE");
                    }
                    norm += number * number;
                    coordinates.add(Double.toString(number));
                }
                if (Math.abs(norm - 1) > 0.001) {
                    throw new KnowledgeRetrievalUnavailableException("MODEL_UNAVAILABLE");
                }
                vectors.add("[" + String.join(",", coordinates) + "]");
            }
            return List.copyOf(vectors);
        } catch (RuntimeException exception) {
            throw new KnowledgeRetrievalUnavailableException("MODEL_UNAVAILABLE");
        }
    }
}
