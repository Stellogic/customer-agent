package com.stellogic.customeragent.investigation;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class EvidenceSufficiencyPolicyTest {
    private static final Instant NOW = Instant.parse("2026-08-29T06:00:00Z");

    @Test
    void acceptsSemanticFactsRegardlessOfCollectionOrder() {
        List<PersistedInvestigationFact> firstPath = sufficientFacts();
        List<PersistedInvestigationFact> secondPath = firstPath.reversed();

        assertThat(EvidenceSufficiencyPolicy.validate(conclusion(), firstPath, NOW)).isNull();
        assertThat(EvidenceSufficiencyPolicy.validate(conclusion(), secondPath, NOW)).isNull();
    }

    @Test
    void rejectsOutOfScopeUnauthorizedExpiredConflictingAndMissingEvidenceWithControlledReasons() {
        assertThat(EvidenceSufficiencyPolicy.validate(conclusion(), List.of(), NOW))
                .isEqualTo("EVIDENCE_OUT_OF_SCOPE");
        assertThat(
                        EvidenceSufficiencyPolicy.validate(
                                conclusion(),
                                replace(
                                        "ORDER",
                                        fact(
                                                "ORDER",
                                                "ORDER-122",
                                                "order:ORDER-122",
                                                "UNKNOWN_SOURCE",
                                                NOW.plusSeconds(60),
                                                "CLEAR")),
                                NOW))
                .isEqualTo("EVIDENCE_SOURCE_UNAUTHORIZED");
        assertThat(
                        EvidenceSufficiencyPolicy.validate(
                                conclusion(),
                                replace(
                                        "ORDER",
                                        fact(
                                                "ORDER",
                                                "ORDER-122",
                                                "order:ORDER-122",
                                                "SPRING_AUTHORIZED_CAPABILITY",
                                                NOW,
                                                "CLEAR")),
                                NOW))
                .isEqualTo("EVIDENCE_EXPIRED");
        assertThat(
                        EvidenceSufficiencyPolicy.validate(
                                conclusion(),
                                replace(
                                        "LOGISTICS_DELAY_SECONDS",
                                        fact(
                                                "LOGISTICS_DELAY_SECONDS",
                                                "288000",
                                                "logistics:ORDER-122",
                                                "SPRING_AUTHORIZED_CAPABILITY",
                                                NOW.plusSeconds(60),
                                                "CONFLICT")),
                                NOW))
                .isEqualTo("FACT_CONFLICT");
        assertThat(
                        EvidenceSufficiencyPolicy.validate(
                                conclusion(),
                                sufficientFacts().stream()
                                        .filter(fact -> !fact.factType().equals("POLICY"))
                                        .toList(),
                                NOW))
                .isEqualTo("REQUIRED_FACT_MISSING");
    }

    @Test
    void confidenceEvidenceCountAndACompletedToolListCannotReplaceApplicability() {
        InvestigationConclusion missingApplicability =
                new InvestigationConclusion(
                        true,
                        DecisionReasonCode.LOGISTICS_DELAY,
                        80,
                        288000,
                        "ORDER-122",
                        List.of("order:ORDER-122", "logistics:ORDER-122"),
                        InvestigationRiskScenario.LOGISTICS_DELAY,
                        "evidence-sufficiency-v1",
                        conclusion().evidence().stream()
                                .map(
                                        item ->
                                                item.evidenceReference().equals("payment:ORDER-122")
                                                        ? new ConclusionEvidence(
                                                                item.evidenceReference(), List.of())
                                                        : item)
                                .toList(),
                        conclusion().customerReply());

        assertThat(EvidenceSufficiencyPolicy.validate(missingApplicability, sufficientFacts(), NOW))
                .isEqualTo("INVALID_EVIDENCE_APPLICABILITY");
    }

    private static List<PersistedInvestigationFact> replace(
            String factType, PersistedInvestigationFact replacement) {
        return sufficientFacts().stream()
                .map(fact -> fact.factType().equals(factType) ? replacement : fact)
                .toList();
    }

    private static List<PersistedInvestigationFact> sufficientFacts() {
        Instant validUntil = NOW.plusSeconds(60);
        return List.of(
                fact("ORDER", "ORDER-122", "order:ORDER-122", validUntil),
                fact("LOGISTICS_DELAY_HOURS", "80", "logistics:ORDER-122", validUntil),
                fact("LOGISTICS_DELAY_SECONDS", "288000", "logistics:ORDER-122", validUntil),
                fact("PAYMENT", "PAID", "payment:ORDER-122", validUntil),
                fact("ORDER_CANCELLATION", "NOT_CANCELLED", "payment:ORDER-122", validUntil),
                fact("REFUND_STATUS", "NOT_FULLY_REFUNDED", "payment:ORDER-122", validUntil),
                fact("EXISTING_COMPENSATION", "false", "compensation:ORDER-122", validUntil),
                fact("PENDING_ACTION_COUNT", "0", "order-actions:ORDER-122", validUntil),
                fact("POLICY", "delay-policy-v1", "policy:delay-policy-v1", validUntil));
    }

    private static PersistedInvestigationFact fact(
            String type, String value, String reference, Instant validUntil) {
        return fact(type, value, reference, "SPRING_AUTHORIZED_CAPABILITY", validUntil, "CLEAR");
    }

    private static PersistedInvestigationFact fact(
            String type,
            String value,
            String reference,
            String source,
            Instant validUntil,
            String conflictStatus) {
        return new PersistedInvestigationFact(
                type, value, reference, source, NOW.minusSeconds(1), validUntil, conflictStatus);
    }

    private static InvestigationConclusion conclusion() {
        List<String> publicEvidence = List.of("order:ORDER-122", "logistics:ORDER-122");
        return new InvestigationConclusion(
                true,
                DecisionReasonCode.LOGISTICS_DELAY,
                80,
                288000,
                "ORDER-122",
                publicEvidence,
                InvestigationRiskScenario.LOGISTICS_DELAY,
                "evidence-sufficiency-v1",
                List.of(
                        evidence("order:ORDER-122", EvidenceApplicability.ORDER_IDENTITY),
                        evidence("logistics:ORDER-122", EvidenceApplicability.DELAY_DURATION),
                        evidence("payment:ORDER-122", EvidenceApplicability.ORDER_ELIGIBILITY),
                        evidence(
                                "compensation:ORDER-122",
                                EvidenceApplicability.EXISTING_COMPENSATION),
                        evidence("order-actions:ORDER-122", EvidenceApplicability.PENDING_ACTIONS),
                        evidence("policy:delay-policy-v1", EvidenceApplicability.POLICY_BASIS)),
                new CustomerReplyEnvelope(
                        "customer-reply-v1",
                        "订单 ORDER-122 的调查已完成，正在等待人工审批。",
                        CustomerReplyIntent.COMPENSATION_REVIEW_PENDING,
                        publicEvidence,
                        false,
                        "ORDER-122"));
    }

    private static ConclusionEvidence evidence(
            String reference, EvidenceApplicability applicability) {
        return new ConclusionEvidence(reference, List.of(applicability));
    }
}
