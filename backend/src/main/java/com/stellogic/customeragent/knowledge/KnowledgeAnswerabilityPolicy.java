package com.stellogic.customeragent.knowledge;

import java.io.IOException;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
final class KnowledgeAnswerabilityPolicy {
    private final JsonNode configuration;

    KnowledgeAnswerabilityPolicy(ObjectMapper json) throws IOException {
        try (var input =
                new ClassPathResource("knowledge-retrieval-policy.json").getInputStream()) {
            configuration = json.readTree(input);
        }
    }

    KnowledgeRetrievalPolicy requireCalibrated() {
        var threshold = configuration.path("threshold");
        if (!"CALIBRATED".equals(configuration.path("status").asText())
                || !KnowledgeEmbeddingGateway.REVISION.equals(
                        configuration.path("modelRevision").asText())
                || !configuration
                        .path("calibrationDatasetSha256")
                        .asText("")
                        .matches("[0-9a-f]{64}")
                || !threshold.isNumber()
                || !Double.isFinite(threshold.asDouble())
                || threshold.asDouble() < -1
                || threshold.asDouble() > 1) {
            throw new KnowledgeRetrievalUnavailableException("CALIBRATION_REQUIRED");
        }
        return new KnowledgeRetrievalPolicy(
                configuration.path("id").asText(),
                configuration.path("calibrationDatasetSha256").asText(),
                threshold.asDouble());
    }
}
