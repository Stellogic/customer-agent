package com.stellogic.customeragent.approval;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

final class ApprovalModels {
    private ApprovalModels() {}

    record QueueItem(
            UUID proposalRevisionId,
            String compensationMethod,
            BigDecimal amount,
            Instant submittedAt,
            Instant expiresAt) {}

    record ClaimCommand(String approverId, UUID revisionId, String requestId, Integer requestedLeaseSeconds) {}

    record LeaseResult(
            UUID proposalRevisionId,
            UUID leaseToken,
            long leaseVersion,
            Instant expiresAt,
            boolean replayed) {}

    record ViewCommand(String approverId, UUID revisionId, UUID leaseToken, long leaseVersion) {}

    record ApprovalView(
            String view,
            String schema,
            String cursor,
            UUID proposalRevisionId,
            int proposalRevision,
            String contentDigest,
            String orderReference,
            String reasonCode,
            int delayHours,
            long delaySeconds,
            String compensationMethod,
            BigDecimal proposedAmount,
            BigDecimal authoritativeAmount,
            String policyVersion,
            String policyTier,
            List<String> eligibilityChecks,
            List<String> evidenceReferences,
            Map<String, Object> evidenceSnapshot,
            List<ResponsibilityEvent> responsibilityChain,
            UUID leaseToken,
            long leaseVersion,
            Instant leaseExpiresAt,
            Instant submittedAt,
            Instant proposalExpiresAt) {}

    record ApprovalViewEvent(
            String epoch, long sequence, String eventType, UUID proposalRevisionId,
            long leaseVersion, String authorityState) {
        String cursor() { return epoch + ":" + sequence; }

        String publicData() {
            return "{\"view\":\"APPROVAL_VIEW\",\"schema\":\"" + epoch
                    + "\",\"payload\":{\"proposalRevisionId\":\"" + proposalRevisionId
                    + "\",\"leaseVersion\":" + leaseVersion + ",\"authorityState\":\""
                    + authorityState + "\"}}";
        }
    }

    record ResponsibilityEvent(String eventType, String actorId, Instant occurredAt, Long leaseVersion) {}

    record ReleaseCommand(
            String approverId, UUID revisionId, UUID leaseToken, long leaseVersion, String requestId) {}

    record ReleaseResult(UUID proposalRevisionId, boolean released, boolean replayed) {}

    record RejectionCommand(
            String approverId,
            UUID revisionId,
            int proposalRevision,
            String contentDigest,
            UUID leaseToken,
            long leaseVersion,
            String requestId,
            String internalReason) {}

    record RejectionResult(
            UUID proposalRevisionId,
            int proposalRevision,
            ProposalDecision decision,
            boolean replayed) {}

    record ApprovalCommand(
            String approverId,
            UUID revisionId,
            int proposalRevision,
            String contentDigest,
            UUID leaseToken,
            long leaseVersion,
            String requestId,
            String internalNote) {}

    record ApprovalResult(
            UUID proposalRevisionId,
            int proposalRevision,
            ProposalDecision decision,
            UUID executionId,
            CompensationExecutionStatus executionStatus,
            boolean replayed) {}

    enum ProposalDecision { APPROVED, REJECTED }

    enum CompensationExecutionStatus { READY, PROCESSING, UNKNOWN, SUCCEEDED, FAILED }
}
