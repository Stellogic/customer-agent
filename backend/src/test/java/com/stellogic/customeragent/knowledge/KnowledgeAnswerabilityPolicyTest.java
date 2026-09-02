package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.InputStream;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class KnowledgeAnswerabilityPolicyTest {
    private static final String MEASURED =
            """
            {"id":"retrieval-logistic-v1","status":"CALIBRATED",
             "modelRevision":"7999e1d3359715c523056ef9478215996d62a620",
             "trainingDatasetSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
             "calibrationDatasetSha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
             "sourceSha":"cccccccccccccccccccccccccccccccccccccccc",
             "featureNames":["dense_max","dense_margin","query_term_coverage","retriever_agreement"],
             "mean":[0.5,0.1,0.5,0.25],"scale":[0.5,0.1,0.5,0.25],
             "coefficients":[2,-1,0.5,3],"intercept":-0.5,"threshold":3}
            """;

    @Test
    void unmeasuredConfigurationCannotFallBackToTheHistoricalCosineThreshold() throws Exception {
        var policy = policy("{\"status\":\"PENDING_CALIBRATION\",\"threshold\":null}");
        assertThatThrownBy(policy::requireCalibrated)
                .isInstanceOf(KnowledgeRetrievalUnavailableException.class)
                .satisfies(
                        error ->
                                assertThat(((KnowledgeRetrievalUnavailableException) error).code())
                                        .isEqualTo("CALIBRATION_REQUIRED"));
    }

    @Test
    void exportedScaleAndWeightsMatchTheHandCalculatedPythonContractIncludingBoundary()
            throws Exception {
        var policy = policy(MEASURED);
        // 测试专用手算参数,不是拟合结果: z=[0.5,1,1,1], dot+b=3。
        var features = List.of(0.75, 0.2, 1.0, 0.5);
        assertThat(policy.score(features)).isEqualTo(3.0);
        assertThat(policy.accepts(features)).isTrue();
        assertThat(
                        policy(MEASURED.replace("\"threshold\":3", "\"threshold\":3.00000001"))
                                .accepts(features))
                .isFalse();
        assertThat(policy.requireCalibrated().calibrationDatasetSha256()).startsWith("bbbb");
    }

    @Test
    void incompatibleFeatureOrderStopsInsteadOfApplyingWeightsToOtherSignals() throws Exception {
        var policy =
                policy(
                        MEASURED.replace(
                                "\"dense_max\",\"dense_margin\"",
                                "\"dense_margin\",\"dense_max\""));
        assertThatThrownBy(policy::requireCalibrated)
                .isInstanceOf(KnowledgeRetrievalUnavailableException.class);
    }

    private static KnowledgeAnswerabilityPolicy policy(String content) throws Exception {
        var source = mock(ObjectMapper.class);
        when(source.readTree(any(InputStream.class)))
                .thenReturn(new ObjectMapper().readTree(content));
        return new KnowledgeAnswerabilityPolicy(source);
    }
}
