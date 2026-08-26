@{
    LogicalCallLimit = 43
    ProviderAttemptLimit = 49
    CostLimitMicros = 400000
    Scenarios = @(
        @{ File = 'e2e/issue124.offline-fullstack-readiness.spec.ts'; Title = '客户通过真实全栈完成安全自动回复' }
        @{ File = 'e2e/issue124.offline-fullstack-readiness.spec.ts'; Title = '客户澄清在原工单恢复' }
        @{ File = 'e2e/issue124.offline-fullstack-readiness.spec.ts'; Title = '客户人工意图停止自动处理' }
        @{
            File = 'e2e/issue80.approval-separation.spec.ts'
            Title = '双角色不能审批本人参与的派生版本'
            Fixture = 'scripts/fixtures/issue80-browser.sql'
        }
        @{ File = 'e2e/issue129.flash-customer-communication.spec.ts'; Title = '客户人工偏好围栏真实 Flash 迟到自动回复' }
    )
}
