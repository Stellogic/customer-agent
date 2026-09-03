package com.stellogic.customeragent.ticket;

import static com.stellogic.customeragent.identity.HumanTestPrincipals.session;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CustomerIntakeV2ApiTest {
    private static final UUID INTAKE_ID = UUID.fromString("15200000-0000-0000-0000-000000000001");
    private static final UUID TICKET_ID = UUID.fromString("15200000-0000-0000-0000-000000000002");
    private final CustomerIntakeService service =
            org.mockito.Mockito.mock(CustomerIntakeService.class);
    private final MockMvc mvc =
            MockMvcBuilders.standaloneSetup(new CustomerIntakeV2Controller(service))
                    .setControllerAdvice(new CustomerTicketExceptionHandler())
                    .defaultRequest(post("/").session(session("customer-demo")))
                    .build();

    @Test
    void startsWithNaturalLanguageAndReturnsOnlyAConfirmableCandidate() throws Exception {
        when(service.start(any()))
                .thenReturn(
                        new CustomerIntakeSnapshot(
                                INTAKE_ID,
                                "READY_TO_CONFIRM",
                                "ORDER-DELAY-001",
                                "配送中的合成订单",
                                java.util.List.of(
                                        new ProposedIntakeIssue("LOGISTICS_DELAY", "物流已经延迟多日")),
                                "我理解为 ORDER-DELAY-001 的物流延迟问题，请确认是否正确。",
                                java.util.List.of(),
                                null,
                                java.util.List.of(),
                                java.util.List.of(),
                                0,
                                0,
                                1,
                                false));

        mvc.perform(
                        post("/api/customer/v2/intakes")
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-152-start")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"customer-intake-v4",
                                          "message":"我的包裹好几天没动了，帮我看看"
                                        }
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.schema").value("customer-intake-v4"))
                .andExpect(jsonPath("$.intakeId").value(INTAKE_ID.toString()))
                .andExpect(jsonPath("$.status").value("READY_TO_CONFIRM"))
                .andExpect(jsonPath("$.candidateOrder.reference").value("ORDER-DELAY-001"))
                .andExpect(jsonPath("$.candidateOrder.summary").value("配送中的合成订单"))
                .andExpect(jsonPath("$.issues.length()").value(1))
                .andExpect(jsonPath("$.ticketIds.length()").value(0))
                .andExpect(jsonPath("$.ticketId").doesNotExist())
                .andExpect(jsonPath("$.confirmed").value(false));
    }

    @Test
    void naturalLanguageAndQuickConfirmationUseTheSameMessageCommand() throws Exception {
        when(service.reply(any()))
                .thenReturn(
                        new CustomerIntakeSnapshot(
                                INTAKE_ID,
                                "CONFIRMED",
                                "ORDER-DELAY-001",
                                "配送中的合成订单",
                                java.util.List.of(
                                        new ProposedIntakeIssue("LOGISTICS_DELAY", "物流已经延迟多日")),
                                "已确认，客服工单正在独立处理。",
                                java.util.List.of(TICKET_ID),
                                UUID.fromString("15300000-0000-0000-0000-000000000003"),
                                java.util.List.of(),
                                java.util.List.of(),
                                0,
                                1,
                                4,
                                false));

        mvc.perform(
                        post("/api/customer/v2/intakes/{intakeId}/messages", INTAKE_ID)
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-152-confirm")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"customer-intake-v4","message":"可以，就按这个处理","expectedVersion":3}
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("CONFIRMED"))
                .andExpect(jsonPath("$.ticketId").doesNotExist())
                .andExpect(jsonPath("$.ticketIds[0]").value(TICKET_ID.toString()))
                .andExpect(
                        jsonPath("$.sharedIntakeRecordId")
                                .value("15300000-0000-0000-0000-000000000003"))
                .andExpect(jsonPath("$.confirmed").value(true));
    }

    @Test
    void exposesAllProposedIssuesAndTheAtomicTicketCount() throws Exception {
        when(service.start(any()))
                .thenReturn(
                        new CustomerIntakeSnapshot(
                                INTAKE_ID,
                                "READY_TO_CONFIRM",
                                "ORDER-MULTI-001",
                                "配送中的合成订单",
                                java.util.List.of(
                                        new ProposedIntakeIssue("PACKAGE_NOT_RECEIVED", "包裹未收到"),
                                        new ProposedIntakeIssue("DUPLICATE_CHARGE", "疑似重复扣款")),
                                "请确认，确认后将创建 2 张工单。",
                                java.util.List.of(),
                                null,
                                java.util.List.of(),
                                java.util.List.of(),
                                0,
                                0,
                                1,
                                false));

        mvc.perform(
                        post("/api/customer/v2/intakes")
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-153-start")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"customer-intake-v4","message":"包裹未收到且重复扣款"}
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.schema").value("customer-intake-v4"))
                .andExpect(jsonPath("$.issues[0].kind").value("PACKAGE_NOT_RECEIVED"))
                .andExpect(jsonPath("$.issues[1].kind").value("DUPLICATE_CHARGE"))
                .andExpect(jsonPath("$.expectedTicketCount").value(2));
    }

    @Test
    void idempotencyConflictReturnsTheRecoverableAuthoritativeResult() throws Exception {
        UUID sharedRecordId = UUID.fromString("15300000-0000-0000-0000-000000000003");
        CustomerIntakeSnapshot authoritative =
                new CustomerIntakeSnapshot(
                        INTAKE_ID,
                        "CONFIRMED",
                        "ORDER-MULTI-001",
                        "配送中的合成订单",
                        java.util.List.of(
                                new ProposedIntakeIssue("PACKAGE_NOT_RECEIVED", "包裹未收到"),
                                new ProposedIntakeIssue("DUPLICATE_CHARGE", "重复扣款")),
                        "已确认，2 张客服工单已原子创建并开始独立处理。",
                        java.util.List.of(
                                TICKET_ID, UUID.fromString("15300000-0000-0000-0000-000000000004")),
                        sharedRecordId,
                        java.util.List.of(),
                        java.util.List.of(),
                        0,
                        1,
                        4,
                        true);
        when(service.reply(any()))
                .thenThrow(new IntakeRequestIdentityConflictException(authoritative));

        mvc.perform(
                        post("/api/customer/v2/intakes/{intakeId}/messages", INTAKE_ID)
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "conflicting-key")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"customer-intake-v4","message":"不同参数","expectedVersion":3}
                                        """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.replayed").value(true))
                .andExpect(jsonPath("$.ticketIds.length()").value(2))
                .andExpect(jsonPath("$.sharedIntakeRecordId").value(sharedRecordId.toString()));
    }

    @Test
    void resolvesDuplicateOnlyAfterAnExplicitCustomerChoice() throws Exception {
        UUID existingTicketId = UUID.fromString("15400000-0000-0000-0000-000000000001");
        when(service.resolveDuplicate(any()))
                .thenReturn(
                        new CustomerIntakeSnapshot(
                                INTAKE_ID,
                                "CONFIRMED",
                                "ORDER-DELAY-001",
                                "配送中的合成订单",
                                java.util.List.of(),
                                "已继续既有工单，没有创建重复工单。",
                                java.util.List.of(),
                                null,
                                java.util.List.of(),
                                java.util.List.of(existingTicketId),
                                0,
                                1,
                                4,
                                false));

        mvc.perform(
                        post("/api/customer/v2/intakes/{intakeId}/duplicate-resolution", INTAKE_ID)
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "issue-154-duplicate")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {
                                          "schema":"customer-intake-v4",
                                          "existingTicketId":"15400000-0000-0000-0000-000000000001",
                                          "action":"CONTINUE_EXISTING",
                                          "expectedVersion":3
                                        }
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.ticketIds.length()").value(0))
                .andExpect(jsonPath("$.routedTicketIds[0]").value(existingTicketId.toString()))
                .andExpect(jsonPath("$.confirmed").value(true));
    }

    @Test
    void restoresAnInProgressMultiOrderIntake() throws Exception {
        when(service.snapshot("customer-demo", INTAKE_ID))
                .thenReturn(
                        new CustomerIntakeSnapshot(
                                INTAKE_ID,
                                "READY_TO_CONFIRM",
                                "ORDER-DELAY-002",
                                "配送中的合成订单",
                                java.util.List.of(
                                        new ProposedIntakeIssue("LOGISTICS_DELAY", "物流延迟")),
                                "原始描述已保留，请重新确认下一订单与问题集合。",
                                java.util.List.of(TICKET_ID),
                                UUID.fromString("15400000-0000-0000-0000-000000000002"),
                                java.util.List.of(),
                                java.util.List.of(),
                                0,
                                1,
                                3,
                                false));

        mvc.perform(
                        get("/api/customer/v2/intakes/{intakeId}", INTAKE_ID)
                                .principal(customer("customer-demo")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.candidateOrder.reference").value("ORDER-DELAY-002"))
                .andExpect(jsonPath("$.ticketIds[0]").value(TICKET_ID.toString()))
                .andExpect(jsonPath("$.completedOrderCount").value(1))
                .andExpect(jsonPath("$.confirmed").value(false));
    }

    @Test
    void listsOnlyTheAuthenticatedCustomersRecoverableIntakesWithHistory() throws Exception {
        when(service.recoveryIndex("customer-demo"))
                .thenReturn(
                        new CustomerIntakeRecoveryIndex(
                                java.util.List.of(),
                                java.util.List.of(
                                        new RecoverableCustomerIntake(
                                                new CustomerIntakeSnapshot(
                                                        INTAKE_ID,
                                                        "READY_TO_CONFIRM",
                                                        "ORDER-DELAY-001",
                                                        "配送中的合成订单",
                                                        java.util.List.of(
                                                                new ProposedIntakeIssue(
                                                                        "LOGISTICS_DELAY", "物流延迟")),
                                                        "请重新确认变化后的订单事实。",
                                                        java.util.List.of(),
                                                        null,
                                                        java.util.List.of(),
                                                        java.util.List.of(),
                                                        0,
                                                        0,
                                                        3,
                                                        false),
                                                3,
                                                "ARCHIVED",
                                                Instant.parse("2026-08-27T00:00:00Z"),
                                                Instant.parse("2026-08-27T00:00:00Z"),
                                                false,
                                                java.util.List.of(
                                                        new IntakeConversationMessage(
                                                                "CUSTOMER",
                                                                "物流延迟了",
                                                                Instant.parse(
                                                                        "2026-08-20T00:00:00Z")),
                                                        new IntakeConversationMessage(
                                                                "AGENT",
                                                                "请确认我的理解。",
                                                                Instant.parse(
                                                                        "2026-08-20T00:00:01Z")))))));

        mvc.perform(get("/api/customer/v2/intakes/recovery").principal(customer("customer-demo")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.schema").value("customer-intake-recovery-v1"))
                .andExpect(jsonPath("$.active.length()").value(0))
                .andExpect(jsonPath("$.archived[0].intake.intakeId").value(INTAKE_ID.toString()))
                .andExpect(jsonPath("$.archived[0].version").value(3))
                .andExpect(jsonPath("$.archived[0].retentionState").value("ARCHIVED"))
                .andExpect(jsonPath("$.archived[0].messages.length()").value(2));
    }

    @Test
    void restoresAnArchivedIntakeAgainstItsStableVersion() throws Exception {
        when(service.restore(any()))
                .thenReturn(
                        new RecoverableCustomerIntake(
                                new CustomerIntakeSnapshot(
                                        INTAKE_ID,
                                        "READY_TO_CONFIRM",
                                        "ORDER-DELAY-001",
                                        "配送中的合成订单",
                                        java.util.List.of(
                                                new ProposedIntakeIssue("LOGISTICS_DELAY", "物流延迟")),
                                        "订单事实已变化，请重新确认。",
                                        java.util.List.of(),
                                        null,
                                        java.util.List.of(),
                                        java.util.List.of(),
                                        0,
                                        0,
                                        4,
                                        false),
                                4,
                                "ACTIVE",
                                Instant.parse("2026-09-04T00:00:00Z"),
                                null,
                                true,
                                java.util.List.of()));

        mvc.perform(
                        post("/api/customer/v2/intakes/{intakeId}/restore", INTAKE_ID)
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "restore-155")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"customer-intake-recovery-v1","expectedVersion":3}
                                        """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.version").value(4))
                .andExpect(jsonPath("$.retentionState").value("ACTIVE"))
                .andExpect(jsonPath("$.factsChanged").value(true))
                .andExpect(jsonPath("$.intake.confirmed").value(false));
    }

    @Test
    void rejectsFractionalRestoreVersionsInsteadOfTruncatingThem() throws Exception {
        mvc.perform(
                        post("/api/customer/v2/intakes/{intakeId}/restore", INTAKE_ID)
                                .principal(customer("customer-demo"))
                                .header("Idempotency-Key", "restore-fractional")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        """
                                        {"schema":"customer-intake-recovery-v1","expectedVersion":3.9}
                                        """))
                .andExpect(status().isBadRequest());
    }

    private static UsernamePasswordAuthenticationToken customer(String customerId) {
        return new UsernamePasswordAuthenticationToken(customerId, "n/a");
    }
}
