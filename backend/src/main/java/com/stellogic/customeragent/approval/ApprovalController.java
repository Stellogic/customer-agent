package com.stellogic.customeragent.approval;

import java.util.List;
import com.stellogic.customeragent.identity.SyntheticApprovers;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/approver/compensation-proposals")
public final class ApprovalController {
    private final ApprovalService service;

    ApprovalController(ApprovalService service) {
        this.service = service;
    }

    @GetMapping
    List<ApprovalModels.QueueItem> queue(
            @RequestHeader(value = "X-Synthetic-Approver-Id", required = false) String approverId) {
        requireApprover(approverId);
        return service.queue();
    }

    @PostMapping("/{revisionId}/claims")
    ResponseEntity<ApprovalModels.LeaseResult> claim(
            @RequestHeader(value = "X-Synthetic-Approver-Id", required = false) String approverId,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID revisionId,
            @RequestBody(required = false) ClaimRequest body) {
        String approver = requireApprover(approverId);
        String stableRequestId = requireRequestId(requestId);
        Integer leaseSeconds = body == null ? null : body.requestedLeaseSeconds();
        ApprovalModels.LeaseResult result = service.claim(
                new ApprovalModels.ClaimCommand(approver, revisionId, stableRequestId, leaseSeconds));
        return ResponseEntity.status(result.replayed() ? HttpStatus.OK : HttpStatus.CREATED).body(result);
    }

    @GetMapping("/{revisionId}/approval-view")
    ApprovalModels.ApprovalView view(
            @RequestHeader(value = "X-Synthetic-Approver-Id", required = false) String approverId,
            @RequestHeader(value = "X-Approval-Lease-Token", required = false) UUID leaseToken,
            @RequestHeader(value = "X-Approval-Lease-Version", required = false) Long leaseVersion,
            @PathVariable UUID revisionId) {
        if (leaseToken == null || leaseVersion == null || leaseVersion < 1) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "current approval lease required");
        }
        return service.view(new ApprovalModels.ViewCommand(
                requireApprover(approverId), revisionId, leaseToken, leaseVersion));
    }

    @PostMapping("/{revisionId}/release")
    ApprovalModels.ReleaseResult release(
            @RequestHeader(value = "X-Synthetic-Approver-Id", required = false) String approverId,
            @RequestHeader(value = "X-Approval-Lease-Token", required = false) UUID leaseToken,
            @RequestHeader(value = "X-Approval-Lease-Version", required = false) Long leaseVersion,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID revisionId) {
        if (leaseToken == null || leaseVersion == null || leaseVersion < 1) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "current approval lease required");
        }
        return service.release(new ApprovalModels.ReleaseCommand(
                requireApprover(approverId), revisionId, leaseToken, leaseVersion,
                requireRequestId(requestId)));
    }

    @PostMapping("/{revisionId}/reject")
    ApprovalModels.RejectionResult reject(
            @RequestHeader(value = "X-Synthetic-Approver-Id", required = false) String approverId,
            @RequestHeader(value = "X-Approval-Lease-Token", required = false) UUID leaseToken,
            @RequestHeader(value = "X-Approval-Lease-Version", required = false) Long leaseVersion,
            @RequestHeader(value = "Idempotency-Key", required = false) String requestId,
            @PathVariable UUID revisionId,
            @RequestBody(required = false) RejectionRequest body) {
        if (leaseToken == null || leaseVersion == null || leaseVersion < 1) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "current approval lease required");
        }
        if (body == null || body.proposalRevision() == null || body.proposalRevision() < 1
                || body.contentDigest() == null || !body.contentDigest().matches("[0-9a-f]{64}")
                || body.internalReason() == null || body.internalReason().isBlank()
                || body.internalReason().trim().length() > 1000) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "valid rejection decision required");
        }
        return service.reject(new ApprovalModels.RejectionCommand(
                requireApprover(approverId), revisionId, body.proposalRevision(), body.contentDigest(),
                leaseToken, leaseVersion, requireRequestId(requestId), body.internalReason().trim()));
    }

    private static String requireApprover(String approverId) {
        if (approverId == null || !SyntheticApprovers.contains(approverId.trim())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "approver identity required");
        }
        return approverId.trim();
    }

    private static String requireRequestId(String requestId) {
        if (requestId == null || requestId.isBlank() || requestId.length() > 200) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "stable request identity required");
        }
        return requestId.trim();
    }

    record ClaimRequest(Integer requestedLeaseSeconds) {}

    record RejectionRequest(Integer proposalRevision, String contentDigest, String internalReason) {}
}
