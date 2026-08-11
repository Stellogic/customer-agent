package com.stellogic.customeragent.approval;

import java.util.List;

interface ApprovalService {
    List<ApprovalModels.QueueItem> queue();

    ApprovalModels.LeaseResult claim(ApprovalModels.ClaimCommand command);

    ApprovalModels.ApprovalView view(ApprovalModels.ViewCommand command);

    ApprovalModels.ReleaseResult release(ApprovalModels.ReleaseCommand command);

    ApprovalModels.RejectionResult reject(ApprovalModels.RejectionCommand command);
}
