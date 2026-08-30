package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.InputStream;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class KnowledgeAnswerabilityPolicyTest {
    @Test
    void unmeasuredConfigurationCannotFallBackToAGuessedThreshold() throws Exception {
        var json = new ObjectMapper();
        var source = mock(ObjectMapper.class);
        when(source.readTree(any(InputStream.class)))
                .thenReturn(
                        json.readTree("{\"status\":\"PENDING_CALIBRATION\",\"threshold\":null}"));
        var policy = new KnowledgeAnswerabilityPolicy(source);
        assertThatThrownBy(policy::requireCalibrated)
                .isInstanceOf(KnowledgeRetrievalUnavailableException.class)
                .satisfies(
                        error ->
                                assertThat(((KnowledgeRetrievalUnavailableException) error).code())
                                        .isEqualTo("CALIBRATION_REQUIRED"));
    }

    @Test
    void usesMeasuredThresholdAndKeepsItsProvenance() throws Exception {
        var json = new ObjectMapper();
        var source = mock(ObjectMapper.class);
        when(source.readTree(any(InputStream.class)))
                .thenReturn(
                        json.readTree(
                                """
                                {"id":"independent-cosine-v1","status":"CALIBRATED",
                                 "modelRevision":"7999e1d3359715c523056ef9478215996d62a620",
                                 "calibrationDatasetSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                                 "threshold":0.61}
                                """));
        var result = new KnowledgeAnswerabilityPolicy(source).requireCalibrated();
        assertThat(result.threshold()).isEqualTo(0.61);
        assertThat(result.calibrationDatasetSha256()).hasSize(64);
    }
}
