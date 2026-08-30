package com.stellogic.customeragent.knowledge;

import java.io.IOException;
import java.util.List;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
final class KnowledgeAnswerabilityPolicy {
    private final JsonNode configuration;

    KnowledgeAnswerabilityPolicy(ObjectMapper json) throws IOException {
        try (var input =
                new ClassPathResource("knowledge-answerability-logistic.json").getInputStream()) {
            configuration = json.readTree(input);
        }
    }

    KnowledgeRetrievalPolicy requireCalibrated() {
        if (!"CALIBRATED".equals(configuration.path("status").asText())
                || !"retrieval-logistic-v1".equals(configuration.path("id").asText())
                || !KnowledgeEmbeddingGateway.REVISION.equals(
                        configuration.path("modelRevision").asText())
                || !configuration
                        .path("calibrationDatasetSha256")
                        .asText("")
                        .matches("[0-9a-f]{64}")
                || !configuration.path("trainingDatasetSha256").asText("").matches("[0-9a-f]{64}")
                || !configuration.path("sourceSha").asText("").matches("[0-9a-f]{40}")
                || !finite(configuration.path("threshold"))
                || !finite(configuration.path("intercept"))) {
            throw new KnowledgeRetrievalUnavailableException("CALIBRATION_REQUIRED");
        }
        for (String key : List.of("featureNames", "mean", "scale", "coefficients")) {
            if (!configuration.path(key).isArray() || configuration.path(key).size() != 4) {
                throw new KnowledgeRetrievalUnavailableException("CALIBRATION_REQUIRED");
            }
        }
        for (int index = 0; index < 4; index++) {
            if (!KnowledgeAnswerabilityFeatures.NAMES
                            .get(index)
                            .equals(configuration.path("featureNames").get(index).asText())
                    || !finite(configuration.path("mean").get(index))
                    || !finite(configuration.path("coefficients").get(index))
                    || !finite(configuration.path("scale").get(index))
                    || configuration.path("scale").get(index).asDouble() <= 0) {
                throw new KnowledgeRetrievalUnavailableException("CALIBRATION_REQUIRED");
            }
        }
        return new KnowledgeRetrievalPolicy(
                configuration.path("id").asText(),
                configuration.path("calibrationDatasetSha256").asText(),
                configuration.path("threshold").asDouble());
    }

    double score(List<Double> features) {
        requireCalibrated();
        if (features.size() != 4 || features.stream().anyMatch(value -> !Double.isFinite(value))) {
            throw new KnowledgeRetrievalUnavailableException("ANSWERABILITY_UNAVAILABLE");
        }
        double result = configuration.path("intercept").asDouble();
        for (int index = 0; index < 4; index++) {
            double normalized =
                    (features.get(index) - configuration.path("mean").get(index).asDouble())
                            / configuration.path("scale").get(index).asDouble();
            result += normalized * configuration.path("coefficients").get(index).asDouble();
        }
        if (!Double.isFinite(result)) {
            throw new KnowledgeRetrievalUnavailableException("ANSWERABILITY_UNAVAILABLE");
        }
        return result;
    }

    boolean accepts(List<Double> features) {
        return score(features) >= configuration.path("threshold").asDouble();
    }

    private static boolean finite(JsonNode value) {
        return value.isNumber() && Double.isFinite(value.asDouble());
    }
}
