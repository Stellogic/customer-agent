@{
    ParallelSafe = @(
        'e2e/issue80.static-states.parallel-safe.spec.ts'
        'e2e/issue80.unauthenticated-routes.parallel-safe.spec.ts'
        'e2e/issue191.state-gallery.parallel-safe.spec.ts'
    )
    Serial = @(
        'e2e/issue80.identity-shells.spec.ts'
        'e2e/issue80.session-lifecycle.spec.ts'
        'e2e/issue80.session-restart-expiry.spec.ts'
        'e2e/issue80.business-boundaries.spec.ts'
        'e2e/issue80.approval-separation.spec.ts'
        'e2e/issue80.sse-revocation.spec.ts'
        'e2e/issue98.customer-help-center.spec.ts'
        'e2e/issue99.support-workbench.spec.ts'
        'e2e/issue100.approval-workbench.spec.ts'
        'e2e/issue101.cross-role-acceptance.spec.ts'
        'e2e/issue124.offline-fullstack-readiness.spec.ts'
        'e2e/issue152.natural-language-intake.spec.ts'
        'e2e/issue153.atomic-multi-issue-intake.spec.ts'
        'e2e/issue154.duplicate-multi-order-intake.spec.ts'
        'e2e/issue155.intake-recovery.spec.ts'
        'e2e/issue156.intake-assistance.spec.ts'
        'e2e/issue157.order-ticket-groups.spec.ts'
        'e2e/issue159.public-reply-stream.spec.ts'
        'e2e/issue162.auto-resolution.spec.ts'
        'e2e/issue163.persistent-support-replies.spec.ts'
        'e2e/issue164.standard-compensation.spec.ts'
        'e2e/issue166.knowledge-catalog.spec.ts'
        'e2e/issue190.hybrid-retrieval.spec.ts'
        'e2e/issue173.full-stack.spec.ts'
        'e2e/issue173.auto-resolution-clock.spec.ts'
        'e2e/issue192.customer-help-docs.spec.ts'
        'e2e/issue193.internal-shell.spec.ts'
    )
    Excluded = @{
        'e2e/issue129.flash-customer-communication.spec.ts' = '仅由显式授权的真实模型验收脚本运行，不属于离线完整门禁。'
    }
}
