package com.stellogic.customeragent.investigation;

import java.time.Instant;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class EvidenceSufficiencyPolicy {
    static final String VERSION = "evidence-sufficiency-v1";
    private static final String AUTHORIZED_SOURCE = "SPRING_AUTHORIZED_CAPABILITY";
    private static final Map<String, EvidenceApplicability> REQUIRED_FACTS =
            Map.of(
                    "ORDER", EvidenceApplicability.ORDER_IDENTITY,
                    "LOGISTICS_DELAY_HOURS", EvidenceApplicability.DELAY_DURATION,
                    "LOGISTICS_DELAY_SECONDS", EvidenceApplicability.DELAY_DURATION,
                    "PAYMENT", EvidenceApplicability.ORDER_ELIGIBILITY,
                    "ORDER_CANCELLATION", EvidenceApplicability.ORDER_ELIGIBILITY,
                    "REFUND_STATUS", EvidenceApplicability.ORDER_ELIGIBILITY,
                    "EXISTING_COMPENSATION", EvidenceApplicability.EXISTING_COMPENSATION,
                    "PENDING_ACTION_COUNT", EvidenceApplicability.PENDING_ACTIONS,
                    "POLICY", EvidenceApplicability.POLICY_BASIS);

    private EvidenceSufficiencyPolicy() {}

    static String validate(
            InvestigationConclusion conclusion,
            List<PersistedInvestigationFact> facts,
            Instant now) {
        if (conclusion.riskScenario() != InvestigationRiskScenario.LOGISTICS_DELAY
                || !VERSION.equals(conclusion.sufficiencyPolicyVersion())) {
            return "UNSUPPORTED_RISK_SCENARIO";
        }
        String shapeFailure = validateEvidenceShape(conclusion.evidence());
        if (shapeFailure != null) return shapeFailure;
        if (facts.isEmpty()) return "EVIDENCE_OUT_OF_SCOPE";

        Map<String, PersistedInvestigationFact> factsByType = new HashMap<>();
        Map<String, List<PersistedInvestigationFact>> factsByReference = new HashMap<>();
        for (PersistedInvestigationFact fact : facts) {
            factsByType.put(fact.factType(), fact);
            factsByReference
                    .computeIfAbsent(
                            fact.evidenceReference(), ignored -> new java.util.ArrayList<>())
                    .add(fact);
        }
        if (!factsByType.keySet().containsAll(REQUIRED_FACTS.keySet())) {
            return "REQUIRED_FACT_MISSING";
        }

        Map<String, ConclusionEvidence> evidenceByReference = new HashMap<>();
        for (ConclusionEvidence item : conclusion.evidence()) {
            evidenceByReference.put(item.evidenceReference(), item);
            List<PersistedInvestigationFact> referencedFacts =
                    factsByReference.get(item.evidenceReference());
            if (referencedFacts == null || referencedFacts.isEmpty()) {
                return "EVIDENCE_OUT_OF_SCOPE";
            }
        }
        for (PersistedInvestigationFact fact : facts) {
            if (!AUTHORIZED_SOURCE.equals(fact.sourceAuthority())) {
                return "EVIDENCE_SOURCE_UNAUTHORIZED";
            }
            if (!fact.validUntil().isAfter(now)) return "EVIDENCE_EXPIRED";
            if (!"CLEAR".equals(fact.conflictStatus())) return "FACT_CONFLICT";
        }
        for (Map.Entry<String, EvidenceApplicability> requirement : REQUIRED_FACTS.entrySet()) {
            PersistedInvestigationFact fact = factsByType.get(requirement.getKey());
            ConclusionEvidence item = evidenceByReference.get(fact.evidenceReference());
            if (item == null || !item.applicability().contains(requirement.getValue())) {
                return "INVALID_EVIDENCE_APPLICABILITY";
            }
        }
        return null;
    }

    private static String validateEvidenceShape(List<ConclusionEvidence> evidence) {
        if (evidence == null || evidence.isEmpty()) return "INVALID_EVIDENCE_APPLICABILITY";
        Set<String> references = new HashSet<>();
        for (ConclusionEvidence item : evidence) {
            if (item == null
                    || item.evidenceReference() == null
                    || item.evidenceReference().isBlank()
                    || !references.add(item.evidenceReference())
                    || item.applicability() == null
                    || item.applicability().isEmpty()
                    || item.applicability().stream().anyMatch(java.util.Objects::isNull)
                    || EnumSet.copyOf(item.applicability()).size() != item.applicability().size()) {
                return "INVALID_EVIDENCE_APPLICABILITY";
            }
        }
        return null;
    }
}

record PersistedInvestigationFact(
        String factType,
        String factValue,
        String evidenceReference,
        String sourceAuthority,
        Instant recordedAt,
        Instant validUntil,
        String conflictStatus) {}
