package com.stellogic.customeragent.approval;

import java.util.List;

interface ApprovalService {
    List<ApprovalModels.QueueItem> queue();

    ApprovalModels.LeaseResult claim(ApprovalModels.ClaimCommand command);

    ApprovalModels.ApprovalView view(ApprovalModels.ViewCommand command);

    List<ApprovalModels.ApprovalViewEvent> events(
            ApprovalModels.ViewCommand command, String afterCursor);

    default void requireCurrentView(ApprovalModels.ViewCommand command) {
        view(command);
    }

    ApprovalModels.ReleaseResult release(ApprovalModels.ReleaseCommand command);

    ApprovalModels.RejectionResult reject(ApprovalModels.RejectionCommand command);

    ApprovalModels.ApprovalResult approve(ApprovalModels.ApprovalCommand command);
}
