package com.stellogic.customeragent.approval;

import java.util.List;
import java.util.Set;
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
    private static final Set<String> APPROVERS = Set.of("approver-demo", "approver-other-demo");
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

    private static String requireApprover(String approverId) {
        if (approverId == null || !APPROVERS.contains(approverId.trim())) {
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
}
