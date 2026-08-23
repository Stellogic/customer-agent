# [规格] 客服工单调查与补偿审批 Agent MVP 首个纵向切片

> 来源：[https://github.com/Stellogic/customer-agent/issues/11](https://github.com/Stellogic/customer-agent/issues/11)
> Issue 状态：CLOSED
> 创建时间：2026-08-09T10:57:08Z
> 最后更新时间：2026-08-11T11:57:23Z
> 同步日期：2026-08-23
> 说明：本文件是 GitHub Issue 正文的只读镜像；项目仍以 GitHub Issue 为规格事实源。

## Problem Statement

客户遇到物流延迟后，需要在一个客服工单中获得可理解、可追踪的调查与补偿结果；当前项目还缺少一条能够同时证明 Agent 调查能力、确定性业务校验、人工审批、补偿幂等、断线恢复和权限隔离的可实施纵向切片。

这个问题不能通过聊天界面或固定 CRUD 演示解决。Agent 不能自行决定补偿资格、金额、审批或执行；客户也不能看到内部调查事实、工具结果、提案草稿或审批责任链。跨 React、Spring Boot 与 LangGraph 的异步流程还必须在重复消息、响应丢失、恢复重放、旧 Agent 处理代次迟到输出和审批并发下保持一致，确保同一补偿意图不会产生第二笔补偿。

项目面向个人学习、简历说明和 3–5 分钟本地面试演示，需要形成可运行、可自动验证且边界诚实的 MVP，而不是声称建成生产级客服平台。

## Solution

提供一条“客户现场创建物流延迟客服工单 → Agent 调查 → Spring 确定性复核 → 审批人批准 → 模拟部分退款首次响应丢失 → 补偿执行器自动对账 → 客户看到唯一成功结果”的完整闭环。

客户使用独立帮助中心查看公开沟通、公开进度、客户澄清请求和最终结果。客服与审批人使用按服务端权限注册页面的内部工作台；首个切片实现审批队列、提案版本审批视图和客服共享队列最小摘要，不实现完整人工客服处理页面。

浏览器只访问 Spring Boot。Spring Boot 是身份、授权、客服工单、Agent 处理代次、调查事实、补偿政策、提案、审批、补偿执行、事务和审计的业务权威。私有 Agent Server 与 LangGraph 只负责编排单次调查、受限工具选择、checkpoint 以及调查内部的 `interrupt/resume`。所有业务读取和写入都通过 Spring 的受限接口完成。

系统使用 Spring 权威快照和按角色分离的 SSE 授权投影视图。审批与补偿执行是独立于 Agent 调查的业务生命周期。所有补偿均需人工审批；批准在同一事务内形成最终审批、额度预占和唯一 `READY` 补偿执行。补偿执行器使用稳定幂等键推进模拟执行；结果未知时进入 `UNKNOWN` 并先对账，禁止创建第二次补偿。

## User Stories

1. As a 客户, I want to submit a logistics-delay complaint as a customer support ticket, so that the issue can be investigated and resolved in one traceable conversation.
2. As a 客户, I want the system to associate my ticket with an eligible order, so that the investigation uses the correct order, logistics and payment facts.
3. As a 客户, I want to see an acknowledgement within the public conversation, so that I know my ticket has been accepted.
4. As a 客户, I want to see understandable public progress, so that I know the investigation is continuing without seeing internal operational details.
5. As a 客户, I want to answer a controlled clarification request in the current ticket, so that an ambiguous order can be resolved without opening a new request.
6. As a 客户, I want a clarification reply to resume only the current valid investigation, so that stale or unrelated replies cannot restart an old workflow.
7. As a 客户, I want to request human handling, so that autonomous Agent processing stops when I explicitly prefer a person.
8. As a 客户, I want to receive a fixed public explanation when the ticket is safely handed to a human, so that internal failures are not leaked to me.
9. As a 客户, I want to be told when a compensation suggestion is awaiting approval, so that I understand why the final result is not yet available.
10. As a 客户, I want to be told that an uncertain execution result is being automatically confirmed, so that I do not submit the compensation request again.
11. As a 客户, I want to see the final compensation method, amount and masked payment destination only after success is confirmed, so that the result is clear and privacy-preserving.
12. As a 客户, I want my successfully completed ticket to enter the resolved state, so that I can still dispute the same issue during the closure waiting period.
13. As a 客户, I want a reply about the same issue within 72 hours of resolution to reopen the ticket, so that a premature resolution can be corrected.
14. As a 客户, I want a reply after closure or about a different issue to create a related new ticket, so that closed history remains stable.
15. As a 客户, I want only my own public messages, public status and final result to be visible, so that internal notes, evidence, proposals, approvals and Agent internals remain private.
16. As a 客服, I want a shared support queue containing only minimal ticket summaries, so that I can discover handoffs and SLA breaches without gaining premature access to ticket details.
17. As a 客服, I want breached tickets to appear in the shared escalation queue, so that operational attention increases without changing the ticket lifecycle or approving compensation.
18. As an 审批人, I want to see a queue containing only proposal number, method, amount, submission time and expiry, so that I can choose work without viewing the full ticket.
19. As an 审批人, I want to claim a proposal revision with a temporary exclusive approval lease, so that two approvers cannot make conflicting decisions.
20. As an 审批人, I want the approval view to load only after a valid claim, so that proposal evidence follows current responsibility.
21. As an 审批人, I want to review the immutable proposal revision, policy basis, eligibility checks, evidence references and minimal responsibility chain, so that I can make an informed decision.
22. As an 审批人, I want the system to show the amount recalculated by Spring rather than an untrusted Agent amount, so that the decision uses authoritative facts.
23. As an 审批人, I want rejection to require an internal reason, so that the resulting human handoff is accountable.
24. As an 审批人, I want approval and rejection requests to be idempotent and tied to the current lease and proposal revision, so that retries cannot create conflicting decisions.
25. As an 审批人, I want expired, released, replaced or completed approval responsibility to revoke both read and write access, so that stale pages cannot be used.
26. As an 审批人, I want evidence and actions removed immediately after my decision, so that the approval view does not become continuing ticket access.
27. As an 审批人, I want to be unable to execute, retry, reconcile or revoke compensation after approval, so that approval remains separate from execution operations.
28. As the Agent, I want a new processing generation and stable workflow thread for a valid investigation, so that one current business authority can be fenced from older runs.
29. As the Agent, I want to use only allowlisted Spring tools scoped to one ticket and generation, so that I cannot choose my own resource or permission boundary.
30. As the Agent, I want to obtain structured order, payment, logistics, policy and existing-compensation facts, so that the suggestion cites the minimum required evidence.
31. As the Agent, I want to pause with a customer clarification request when the order cannot be uniquely identified, so that I do not guess facts or create a proposal prematurely.
32. As the Agent, I want safe handoff after bounded retries, conflicting facts, invalid tool data or unsupported scenarios, so that failures do not become unauthorized actions.
33. As the Agent, I want to submit a structured compensation suggestion through one restricted command, so that Spring can independently verify every consequential field.
34. As the Agent, I want my generation to finish after Spring accepts the investigation result, so that approval is not represented as an Agent waiting state.
35. As the Agent, I want late outputs from a superseded generation to be rejected and audited, so that replay cannot alter current business state or publish customer messages.
36. As the 补偿执行器, I want one stable execution and idempotency key per approved proposal revision, so that retries and reconciliation refer to the same compensation intent.
37. As the 补偿执行器, I want an ambiguous response to enter `UNKNOWN`, so that an uncertain result is never treated as a safe failure.
38. As the 补偿执行器, I want to reconcile `UNKNOWN` using the same execution identity, so that an already-recorded simulated refund is discovered instead of repeated.
39. As the 补偿执行器, I want to release reserved allowance only after failure is confirmed to mean no compensation occurred, so that another proposal cannot overspend uncertain capacity.
40. As a project reviewer, I want a 3–5 minute demonstration of response loss and automatic reconciliation, so that the project visibly proves more than chat rendering or CRUD.
41. As a project reviewer, I want deterministic automated tests with fake models and fixed tools, so that correctness does not depend on natural-language wording or live model variance.
42. As a project reviewer, I want a small separate real-model smoke/evaluation set, so that Agent integration can be checked without making nondeterministic calls part of ordinary CI.
43. As a project reviewer, I want every critical business transition and responsibility change recorded as an append-only audit event, so that the demonstrated result can be explained after the workflow finishes.
44. As a project reviewer, I want all demo identities and business records to be synthetic, so that the project can be shown without using real customer or payment data.
45. As a project reviewer, I want the local deployment and résumé description to state their actual validation boundary, so that a working MVP is not misrepresented as a production-grade Agent platform.

## Implementation Decisions

### Product scope and demonstration data

- The main scenario is a logistics-delay complaint using preconfigured synthetic order, logistics, payment and policy facts.
- The demonstration order is paid, not cancelled, not fully refunded, has no existing compensation for the same delay cause, has an actual paid amount of `268.00 CNY`, and is delayed by 80 hours.
- The accepted result is a simulated partial original-payment-method refund of `26.80 CNY`. The simulator records the compensation but intentionally loses the first response; automatic reconciliation then finds that same result.
- Money uses decimal amounts precise to cents. Partial refund is 10% of the paid amount, capped at `50.00 CNY`, with the final result rounded to two decimal places.
- The policy tiers are mutually exclusive: less than 24 hours has no compensation; 24 to less than 48 hours gives a 10 CNY coupon; 48 through exactly 72 hours gives a 20 CNY coupon; more than 72 hours gives the capped simulated partial refund. Account balance is excluded from this MVP.
- Every compensation tier requires human approval. The Agent may investigate and suggest but cannot determine final eligibility, approve or execute.

### Ticket lifecycle, handling and service levels

- The support-ticket lifecycle is `NEW`, `INVESTIGATING`, `WAITING_FOR_CUSTOMER`, `WAITING_FOR_EXTERNAL`, `RESOLVED` and `CLOSED`. First response is a time event, not a lifecycle state.
- `RESOLVED` automatically becomes `CLOSED` after 72 continuous hours without a same-issue customer objection. Same-issue public replies during that period reopen to `INVESTIGATING`; internal notes and automated notifications do not reopen. Closed tickets cannot reopen directly.
- First-response objective is 15 continuous minutes and never pauses. Resolution objective is 24 accumulated continuous hours; it pauses only while waiting for the customer and resumes from the elapsed value. Resolution stops the clock, and reopening continues the original elapsed value.
- Crossing 80% creates an SLA warning; crossing 100% creates an irreversible breach. If a current assigned support agent already exists, the warning notifies that agent; this slice does not create an assignment or grant detail access. Breached tickets join the shared support escalation queue. Neither event changes lifecycle state or grants compensation authority.
- Handling mode is orthogonal to lifecycle and is either `AGENT` or `HUMAN`. Customer human preference prevents Agent handback until explicitly cleared.

### Actors, authorization and data boundaries

- Human business actors are customer, support agent and approver. The MVP has no administrator, supervisor, auditor or human compensation-executor role.
- Agent and compensation executor are separate restricted machine actors. They use distinct machine identities and capabilities.
- Customer, support workbench and approval view are separately authorized projections. Queue membership, hidden menus and stream cursors never grant resource access.
- A support agent receives detailed ticket access only through a current active assignment. An approver receives proposal-scoped access only through a current approval lease.
- The default approval lease is 15 minutes and configurable. It is identified by a lease token/version, checked using server time, and cannot extend beyond the pending proposal revision's 24-hour validity.
- The approval decision is bound to an immutable proposal revision and content digest. Rejection requires a reason; approval comment is optional. Decision submission revalidates proposal state, revision, expiry, approver, lease and idempotency request.
- In the same approval transaction, Spring re-reads and validates current order eligibility/state, policy version and tier, available compensation amount, existing compensation and concurrent reservations. Any drift rejects approval, invalidates the stale revision and requires a new revision before another approval attempt.
- A successful approval is final authorization for that revision and atomically creates one `READY` compensation execution plus the allowance reservation. Business actors cannot revoke it or invoke execution recovery operations.
- Only synthetic customer and payment facts are used. No real card number, CVV, bank account, payment token or refund credential is stored. Secrets and authentication material never enter prompts, checkpoints, traces, logs or browser events.

### Spring Boot business authority

- Browser clients call only Spring Boot for authentication, ticket commands, projections, investigation submission, approval commands and SSE.
- Spring owns authoritative business state, authorization, deterministic policy calculation, ticket transitions, processing generations, proposal revisions, approvals, allowance reservation, execution, transactions and append-only audit events.
- Spring re-reads current authoritative facts when accepting an Agent suggestion and again where required by approval/execution invariants. Agent evidence is not transaction-time truth.
- A proposal revision is immutable and binds ticket, order, delay fact, method, amount, reason code, evidence snapshot/references and policy version. Consequential changes create a new revision and supersede the old one.
- One delay cause may have only one active pending or approved-not-complete compensation intent. PostgreSQL transactions and unique constraints arbitrate concurrent tickets and allowance competition.
- Approval and execution are different facts. Execution business states are `READY → PROCESSING → SUCCEEDED | FAILED | UNKNOWN`. From `UNKNOWN`, reconciliation may move to `SUCCEEDED`, or to `FAILED` only after confirming no compensation occurred; exhausted reconciliation remains `UNKNOWN` and raises an out-of-domain operational alert. `FAILED` means no compensation is confirmed and automatic policy is exhausted; normal retry from `UNKNOWN` is forbidden.
- Every business write command uses a stable request or idempotency identity and critical-parameter digest. Reusing an identity with different parameters is a conflict; reusing it with identical parameters returns the existing result.
- Audit events are appended in the same transaction as each business transition and reference business records without copying full conversations, raw tool results or traces.

### Agent Server and LangGraph boundary

- The project uses a private local Agent Server started with `langgraph dev` for development and demonstration. It does not use LangSmith Cloud and does not require a paid Standalone license for MVP completion.
- One Spring processing generation maps to one stable Agent Server thread and may contain multiple framework runs. Thread, run, checkpoint and cursor identifiers are never user identity or authorization credentials.
- Spring creates the generation, stable thread mapping and reliable-submission record in one local transaction, then submits asynchronously. Unknown thread or run submission responses are reconciled by stable client identities rather than by creating a second effective resource.
- LangGraph is responsible for investigation orchestration, allowlisted tool selection, checkpointing and investigation-internal `interrupt/resume`. Compensation approval and execution do not use LangGraph interrupt and are not Agent tools.
- The investigation has four semantic responsibilities: understand and plan structurally; collect restricted facts; form structured facts, evidence references and suggestion; submit the suggestion and end the generation. These responsibilities do not require exactly four graph nodes.
- Spring reauthorizes every Agent tool call using current generation, ticket, operation, handling mode and business state. Old-generation calls and late product events are fenced and audited.
- Checkpoints are operational recovery state, not business truth or audit. Completed, cancelled, superseded or handed-off generations enter the accepted short cleanup lifecycle while Spring retains sufficient business records to explain the result.
- The local development server has demonstrated same-process interrupt/resume and cross-process protocol behavior but has not demonstrated checkpoint survival after forced server restart. That restart guarantee is not an MVP completion requirement.

### Reliable submission, clarification and handoff

- Investigation is asynchronous and independent of the initiating browser connection. Spring returns an accepted/queryable result after committing the generation and reliable submission record; SSE disconnection does not cancel processing.
- Customer clarification is the only MVP use of LangGraph interrupt. A valid deduplicated reply to the current clarification request resumes the same generation/thread; unrelated input, stale replies or human preference do not.
- Bounded tool retries exhausted, conflicting critical facts, invalid tool schemas and unsupported scenarios trigger safe human handoff. Spring changes handling mode, invalidates the generation, publishes a fixed customer message, records a controlled reason code and exposes only a minimal queue summary.
- When the customer explicitly requests human handling, Spring records the current customer human preference, atomically changes handling mode to `HUMAN`, invalidates the current generation, publishes the fixed handoff message and adds the minimal queue summary. Late tool calls and public-message attempts from that generation are rejected and audited.
- When an approver rejects a proposal revision, Spring atomically validates the lease, revision and decision request, records the rejection reason, creates no allowance reservation and no compensation execution, changes the ticket to `HUMAN`, publishes the fixed customer handoff message and adds the minimal queue summary.
- Safe handoff persists a structured investigation summary for future authorized human handling, but the first slice exposes only the agreed minimal queue summary and does not implement support claiming or detailed human handling.

### Product projections and streaming

- React first loads a complete Spring-authoritative projection and its `epoch:sequence` cursor, then consumes SSE for the matching view. SSE improves freshness but is not the sole source of truth.
- `CUSTOMER_PUBLIC`, `SUPPORT_WORKBENCH` and proposal/lease-scoped `APPROVAL_VIEW` have independent projection shapes, event allowlists, epochs and sequences over one underlying business truth.
- Spring maps recognized internal signals to closed product-event types. Unknown types and payloads containing forbidden fields are rejected from the product event log. Prompt, raw model input/output, free-form reasoning, raw tool payloads, checkpoints, tokens and internal thread/run/trace identifiers are not browser product events.
- Event application is sequence-based, never timestamp-based. Duplicate or older sequence numbers are ignored. Gaps, incompatible epoch/view/schema, invalid payload or trimmed history stop incremental application and force a fresh authoritative snapshot.
- Spring rechecks authorization when connecting, replaying and delivering live events. Loss of the currently applicable role, resource relationship, approval lease or other responsibility stops delivery and closes the connection. Cursor values are not authorization.
- Spring fences late events from superseded generations; the support-workbench reducer performs a second defensive rejection.

### React product surfaces

- Customers use an independent help-center shell with help entry points, ticket summary and public ticket conversation. Desktop may use a floating conversation surface and narrow screens a full-screen conversation.
- Support agents and approvers share an internal visual shell but receive distinct server-authorized routes, menus and data. Formal product UI does not contain a free role switcher.
- The customer surface may use Ant Design X presentation components; the internal workbench may use Ant Design components. Candidate exact versions are `@ant-design/x@2.9.0` and `antd@6.5.4`.
- The first slice does not use Ant Design X SDK, Think/ThoughtChain components or a full Ant Design Pro scaffold. The browser never connects to the model or Agent Server.
- The approver surface contains queue and proposal-revision detail. The support surface contains only the shared-queue minimal summary for this slice; complete human support handling remains out of scope.
- Disconnection is visible as potentially stale state. The UI discards noncontinuous incremental state and resynchronizes from the matching Spring projection.

### Candidate technology baseline and deployment boundary

- Candidate baseline is React 19.2.7, Node.js 24.19.0 LTS, TypeScript 6.0.3, Spring Boot 4.1.0, Java 25 LTS, Python 3.13.15, LangGraph 1.2.10, `langgraph-checkpoint-postgres` 3.1.2, `langgraph-checkpoint` 4.2.0 and PostgreSQL 18.4.
- These are candidates supported by official release/dependency evidence, not yet a project-verified complete combination. Exact versions and lockfiles are required; minimum builds and integration tests must promote them to a verified baseline.
- Spring and Agent Server may share one local PostgreSQL instance but use separate databases, accounts and migration permissions. They communicate only through APIs and do not share ORM models, cross-database foreign keys or transactions.
- The deliverable is a locally runnable full-stack Agent MVP and local end-to-end validation, with a recording as demonstration fallback. It must not be described as production high availability, horizontal scalability or disaster recovery.

## Testing Decisions

### Confirmed primary seam

The single primary acceptance seam is the product API and SSE surface exposed by Spring to the browser. This is the highest stable boundary because every human product interaction crosses it, Spring is the business authority, and Agent Server internals are deliberately not a browser contract.

The two final end-to-end tests cross that seam through the React surfaces, real Spring application, migrated PostgreSQL databases, a real local Agent Server/LangGraph runtime, and the simulated compensation executor. The model and business-tool responses may be fake/stubbed for determinism, but the tests must not replace LangGraph with a stub adapter:

1. Create ticket → investigate → submit proposal → claim and approve → execute → confirm one successful compensation → resolve ticket.
2. Create ticket → investigate → approve → simulator records compensation but loses the response → execution becomes `UNKNOWN` → automatic reconciliation finds the existing result → confirm exactly one compensation and the same final customer result.

Lower seams supplement this primary seam only where they give more deterministic or fault-focused proof; they do not create additional product contracts.

### Test quality rules

- Test externally visible behavior, domain transitions, persisted constraints, authorization decisions and published product contracts rather than private methods, graph-node counts, component structure or framework internals.
- Use controllable clocks, deterministic IDs, fake/stub models and fixed tool responses in ordinary CI. Do not assert exact natural-language wording except for controlled public template codes/text required by the contract.
- Security and money invariants are zero-tolerance. A test that only proves the happy-path UI or a throwaway prototype is insufficient.
- PostgreSQL integration tests start from an empty database, run real migrations and exercise transactions, unique constraints, account isolation and actual concurrent requests.
- Contract tests verify semantic rules for generation, request identities, idempotency keys, execution identity, error codes, event versions and authorization, not only JSON field presence.
- Existing throwaway prototypes provide prior art for generation fencing, interrupt/resume, unknown-response reconciliation, event sequence recovery and UI information separation; production tests must independently prove real framework behavior.

### Modules and principal proof layers

- Deterministic domain tests cover compensation tier boundaries, amount precision/cap/rounding, ticket lifecycle, SLA pause/resume, warning/breach thresholds, closure/reopen boundaries, proposal validity and legal/illegal execution transitions.
- Spring + PostgreSQL integration tests cover authorization, rejection of support-ticket detail access without an active assignment, approval lease, immutable proposal revisions, final approval transaction, allowance reservation, execution uniqueness, audit atomicity, reliable submission, unknown-response reconciliation, message deduplication and true concurrent conflicts. Positive assignment creation and revocation flows are deferred to the future human-handling slice.
- Agent graph tests and fixed-case evaluations cover structured outputs, minimum evidence collection, clarification interrupt/resume, safe handoff, allowlisted tools, malformed data, unsupported scenarios, prompt-injection resistance and missing facts.
- Cross-service contract tests and a real local Agent Server adapter smoke cover stable generation/thread mapping, multiple runs, submission and resume request deduplication, tool-call authorization, same-key retry and stale-generation rejection.
- Frontend behavior tests cover role-specific routes and projections, approval claim/expiry/decision, rejection-reason validation, evidence removal after responsibility ends, customer clarification, duplicate/late/gapped events, disconnect notice, snapshot reset, keyboard/focus behavior and narrow-screen behavior.
- A small separate real-model release smoke/evaluation uses fixed synthetic scenarios and judges structured correctness and safety invariants, not verbatim prose.

### Required boundary and failure cases

- Compensation delays immediately below, at and above 24, 48 and 72 hours; partial-refund cap; cent rounding; cancelled, unpaid or fully refunded order; exhausted or concurrently reserved allowance.
- First response at 80% and 100%; resolution timing across waiting-for-customer and waiting-for-external; immediate warning/breach after resume; exactly 72-hour close boundary; close/reply concurrency; reopen without SLA reset.
- Duplicate inbound message, concurrent customer reply, stale clarification reply, duplicate resume, multiple runs in one generation, replaced-generation late tool call and late public-message attempt.
- Approval lease expiry, claim/release/reclaim, stale token, replaced proposal revision, duplicate identical decision, reused request ID with different decision, approve/reject race and evidence access after responsibility ends.
- Approval rejection records the required reason, creates neither allowance reservation nor execution, moves the ticket to `HUMAN`, publishes only the fixed customer handoff message and exposes only the minimal shared-queue summary.
- A customer human request records the preference, moves the ticket to `HUMAN`, invalidates the current generation, rejects and audits late tool/public-message effects, publishes the fixed handoff message and exposes only the minimal shared-queue summary.
- Compensation response loss before/after simulated side effect, repeated execution delivery, same identity with different parameters, `UNKNOWN` normal-retry rejection, reconciliation success, confirmed failure and reconciliation exhaustion.
- Product-event duplicate, old event, gap, incompatible epoch/view/schema, trimmed history, illegal field, unknown raw Agent event, stale-generation event, snapshot/replay race and permission revocation on an existing SSE connection.
- Customer attempts internal routes/APIs; support agent attempts approval; approver attempts full-ticket or execution access; Agent attempts out-of-scope ticket/operation; compensation executor attempts proposal or approval mutation.
- Browser network/build inspection confirms no model key, internal Agent address, raw Agent event, tool payload, checkpoint, reasoning, prompt or internal approval draft is shipped.
- Candidate frontend versions must pass installation, type checking, unit tests, production build, route-level bundle inspection, keyboard/focus, narrow-screen and basic screen-reader smoke checks before being called verified.

## Out of Scope

- Real payment, real refund, money transfer, real logistics-provider integration or any production business data.
- Account-balance compensation, points, exchange, manual transfer and scenarios beyond the selected logistics-delay slice.
- Customer preauthorized delegated approval or any mode in which the Agent approves compensation.
- Support claiming and detailed ticket handling after queue discovery, Agent handback, Agent assist, human creation or modification of compensation proposals and the associated self-approval restriction, the complete human support-agent workbench, supervisor/admin/auditor business UI and global audit-query UI.
- Business-user commands to retry, reconcile, cancel or revoke an approved compensation; correction/reversal after mistaken approval.
- Production multi-tenancy, enterprise identity integration, OAuth2/OIDC/mTLS rollout, internet-exposed Agent Server, multi-region deployment, horizontal-scaling guarantees, disaster recovery, full backup restoration and long-running soak/chaos programs.
- A full LLM evaluation platform, full browser matrix or exhaustive end-to-end coverage of every component and branch.
- LangSmith Cloud, paid Standalone deployment and a guarantee that `langgraph dev` checkpoints survive forced process restart.
- Copying or porting AGPL source, styles or distinctive text from Frappe Helpdesk, Zammad or other reference projects.
- Promoting throwaway prototype HTML/CSS/JavaScript directly into production React code.

## Further Notes

- This specification synthesizes the completed Wayfinder map and decisions in #1 through #10. Later decisions in #4 replace the earlier supervisor notification, revocable approval and human retry statements from #2 and #3.
- The agreed next workflow is `to-tickets`, which should decompose this specification into dependency-aware implementation issues. Tickets should preserve the confirmed Spring API/SSE acceptance seam and expand the risk matrix into concrete preconditions, actions and expected outcomes.
- The main demonstration intentionally uses the response-loss recovery path because it distinguishes the project from a chat or CRUD demo. Demonstration success does not replace automated acceptance.
- The implementation may choose internal class, module and graph-node layouts during ticket refinement as long as the ownership, authorization, data and externally observable contracts above remain intact.
