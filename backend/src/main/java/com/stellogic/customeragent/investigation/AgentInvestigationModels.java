package com.stellogic.customeragent.investigation;

import java.util.List;
import java.util.UUID;

record InvestigationCapabilityCatalog(
        String schemaVersion, List<InvestigationCapabilityDefinition> capabilities) {}

record InvestigationCapabilityDefinition(
        InvestigationCapability name,
        List<InvestigationCapabilityField> parameters,
        List<InvestigationCapabilityField> resultFields) {}

record InvestigationCapabilityField(
        String name, InvestigationCapabilityValueType type, boolean required) {}

enum InvestigationCapabilityValueType {
    STRING,
    INTEGER,
    BOOLEAN,
    STRING_LIST
}

record InvestigationCapabilityParameters(String orderReference) {}

sealed interface InvestigationCapabilityResult
        permits OrderConfirmationResult,
                LogisticsFactsResult,
                PaymentRefundFactsResult,
                CompensationActionsFactsResult,
                ApplicablePolicyResult {}

record OrderConfirmationResult(
        InvestigationCapability capability,
        String matchStatus,
        String orderReference,
        List<String> evidenceRefs)
        implements InvestigationCapabilityResult {}

record LogisticsFactsResult(
        InvestigationCapability capability,
        int delayHours,
        long delaySeconds,
        List<String> evidenceRefs)
        implements InvestigationCapabilityResult {}

record PaymentRefundFactsResult(
        InvestigationCapability capability,
        Boolean paid,
        Boolean cancelled,
        Boolean fullyRefunded,
        List<String> evidenceRefs)
        implements InvestigationCapabilityResult {}

record CompensationActionsFactsResult(
        InvestigationCapability capability,
        Boolean existingCompensation,
        Integer pendingActionCount,
        List<String> evidenceRefs)
        implements InvestigationCapabilityResult {}

record ApplicablePolicyResult(
        InvestigationCapability capability, String policyVersion, List<String> evidenceRefs)
        implements InvestigationCapabilityResult {}

enum InvestigationCapability {
    CONFIRM_ORDER(
            List.of(),
            fields(
                    field("capability", InvestigationCapabilityValueType.STRING),
                    field("matchStatus", InvestigationCapabilityValueType.STRING),
                    field("orderReference", InvestigationCapabilityValueType.STRING),
                    field("evidenceRefs", InvestigationCapabilityValueType.STRING_LIST))),
    READ_LOGISTICS(
            orderReferenceParameter(),
            fields(
                    field("capability", InvestigationCapabilityValueType.STRING),
                    field("delayHours", InvestigationCapabilityValueType.INTEGER),
                    field("delaySeconds", InvestigationCapabilityValueType.INTEGER),
                    field("evidenceRefs", InvestigationCapabilityValueType.STRING_LIST))),
    READ_PAYMENT_AND_REFUNDS(
            orderReferenceParameter(),
            fields(
                    field("capability", InvestigationCapabilityValueType.STRING),
                    field("paid", InvestigationCapabilityValueType.BOOLEAN),
                    field("cancelled", InvestigationCapabilityValueType.BOOLEAN),
                    field("fullyRefunded", InvestigationCapabilityValueType.BOOLEAN),
                    field("evidenceRefs", InvestigationCapabilityValueType.STRING_LIST))),
    READ_COMPENSATION_AND_PENDING_ACTIONS(
            orderReferenceParameter(),
            fields(
                    field("capability", InvestigationCapabilityValueType.STRING),
                    field("existingCompensation", InvestigationCapabilityValueType.BOOLEAN),
                    field("pendingActionCount", InvestigationCapabilityValueType.INTEGER),
                    field("evidenceRefs", InvestigationCapabilityValueType.STRING_LIST))),
    READ_APPLICABLE_POLICY(
            orderReferenceParameter(),
            fields(
                    field("capability", InvestigationCapabilityValueType.STRING),
                    field("policyVersion", InvestigationCapabilityValueType.STRING),
                    field("evidenceRefs", InvestigationCapabilityValueType.STRING_LIST)));

    private final List<InvestigationCapabilityField> parameters;
    private final List<InvestigationCapabilityField> resultFields;

    InvestigationCapability(
            List<InvestigationCapabilityField> parameters,
            List<InvestigationCapabilityField> resultFields) {
        this.parameters = parameters;
        this.resultFields = resultFields;
    }

    InvestigationCapabilityDefinition definition() {
        return new InvestigationCapabilityDefinition(this, parameters, resultFields);
    }

    boolean requiresOrderReference() {
        return !parameters.isEmpty();
    }

    private static List<InvestigationCapabilityField> orderReferenceParameter() {
        return fields(field("orderReference", InvestigationCapabilityValueType.STRING));
    }

    private static InvestigationCapabilityField field(
            String name, InvestigationCapabilityValueType type) {
        return new InvestigationCapabilityField(name, type, true);
    }

    private static List<InvestigationCapabilityField> fields(
            InvestigationCapabilityField... fields) {
        return List.of(fields);
    }
}

record InvestigationConclusion(
        boolean compensationRequired,
        DecisionReasonCode reasonCode,
        int delayHours,
        long delaySeconds,
        String orderReference,
        List<String> evidenceRefs,
        CustomerReplyEnvelope customerReply) {}

record CustomerReplyEnvelope(
        String schemaVersion,
        String body,
        CustomerReplyIntent intent,
        List<String> evidenceRefs,
        boolean escalationRequired,
        String referencedOrder) {}

enum CustomerReplyIntent {
    NO_COMPENSATION_RESOLUTION,
    COMPENSATION_REVIEW_PENDING
}

record ConclusionAcceptance(
        boolean accepted,
        TicketLifecycleState lifecycleState,
        UUID proposalRevisionId,
        Integer proposalRevision,
        ProposalRevisionStatus proposalStatus) {}

enum DecisionReasonCode {
    DELAY_UNDER_24_HOURS,
    LOGISTICS_DELAY
}

enum TicketLifecycleState {
    INVESTIGATING,
    RESOLVED
}

enum ProposalRevisionStatus {
    PENDING_APPROVAL
}
