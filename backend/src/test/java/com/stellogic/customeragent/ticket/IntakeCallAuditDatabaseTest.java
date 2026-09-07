package com.stellogic.customeragent.ticket;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.stellogic.customeragent.closure.ClosureService;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.support.JdbcTransactionManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Runs only against the runner's isolated, Flyway-migrated PostgreSQL database. */
@EnabledIfEnvironmentVariable(
        named = "INTAKE_AUDIT_TEST_DATABASE_URL",
        matches = "jdbc:postgresql:.*")
class IntakeCallAuditDatabaseTest {
    private static final String ORDER = "ORDER-DELAY-001";
    private final ObjectMapper json = new ObjectMapper();

    @Configuration(proxyBeanMethods = false)
    @EnableTransactionManagement(proxyTargetClass = true)
    static class Transactions {}

    @Test
    void restoreRollbackRetainsConsumedUsageAndSuccessfulReplayDoesNotCallAgain() throws Exception {
        var database =
                new DriverManagerDataSource(
                        System.getenv("INTAKE_AUDIT_TEST_DATABASE_URL"),
                        System.getenv("INTAKE_AUDIT_TEST_DATABASE_USER"),
                        System.getenv("INTAKE_AUDIT_TEST_DATABASE_PASSWORD"));
        var jdbc = new JdbcTemplate(database);
        assertThat(
                        jdbc.queryForObject(
                                "select count(*) from flyway_schema_history where success and version = '45'",
                                Integer.class))
                .isEqualTo(1);
        AtomicInteger requests = new AtomicInteger();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext(
                "/runs/wait",
                exchange -> {
                    exchange.getRequestBody().readAllBytes();
                    int call = requests.incrementAndGet();
                    byte[] body = agentResponse(call).getBytes(StandardCharsets.UTF_8);
                    exchange.getResponseHeaders().set("Content-Type", "application/json");
                    exchange.sendResponseHeaders(200, body.length);
                    try (var output = exchange.getResponseBody()) {
                        output.write(body);
                    }
                });
        server.start();
        try (var context = new AnnotationConfigApplicationContext()) {
            context.register(Transactions.class);
            context.registerBean(JdbcTemplate.class, () -> jdbc);
            context.registerBean(
                    PlatformTransactionManager.class, () -> new JdbcTransactionManager(database));
            context.registerBean(Clock.class, Clock::systemUTC);
            context.registerBean(ObjectMapper.class, () -> json);
            context.registerBean(
                    IntakeUnderstandingGateway.class,
                    () ->
                            new AgentServerIntakeUnderstandingGateway(
                                    "http://127.0.0.1:" + server.getAddress().getPort(),
                                    "test-only",
                                    json));
            // These collaborators are not exercised by restore; the gateway, service and database
            // are real.
            context.registerBean(
                    CustomerTicketService.class, () -> mock(CustomerTicketService.class));
            context.registerBean(ClosureService.class, () -> mock(ClosureService.class));
            context.registerBean(IntakeAssistanceService.class);
            context.registerBean(IntakeModelCallAudit.class);
            context.registerBean(JdbcCustomerIntakeService.class);
            context.refresh();
            MockMvc mvc =
                    MockMvcBuilders.standaloneSetup(
                                    new CustomerIntakeV2Controller(
                                            context.getBean(CustomerIntakeService.class)))
                            .setControllerAdvice(new CustomerTicketExceptionHandler())
                            .build();
            var customer =
                    UsernamePasswordAuthenticationToken.authenticated(
                            "customer-demo", "unused", List.of());
            String start =
                    mvc.perform(
                                    post("/api/customer/v2/intakes")
                                            .principal(customer)
                                            .header(
                                                    "Idempotency-Key",
                                                    "audit-start-" + UUID.randomUUID())
                                            .contentType(MediaType.APPLICATION_JSON)
                                            .content(
                                                    """
                                    {"schema":"customer-intake-v4","message":"订单 ORDER-DELAY-001 的物流延迟问题，请核对。"}
                                    """))
                            .andExpect(status().isCreated())
                            .andReturn()
                            .getResponse()
                            .getContentAsString();
            UUID intakeId = UUID.fromString(json.readTree(start).path("intakeId").asText());
            jdbc.update(
                    "update customer_intake set expires_at = clock_timestamp() - interval '1 second' where id = ?",
                    intakeId);
            String archived =
                    mvc.perform(
                                    get("/api/customer/v2/intakes/{id}/recovery", intakeId)
                                            .principal(customer))
                            .andExpect(status().isOk())
                            .andExpect(jsonPath("$.retentionState").value("ARCHIVED"))
                            .andReturn()
                            .getResponse()
                            .getContentAsString();
            long version = json.readTree(archived).path("version").asLong();
            String requestKey = "audit-restore-" + UUID.randomUUID();
            String restoreBody =
                    "{\"schema\":\"customer-intake-recovery-v1\",\"expectedVersion\":"
                            + version
                            + "}";

            // The second HTTP response is valid CONFIRM output but invalid for restoring an intake.
            mvc.perform(
                            post("/api/customer/v2/intakes/{id}/restore", intakeId)
                                    .principal(customer)
                                    .header("Idempotency-Key", requestKey)
                                    .contentType(MediaType.APPLICATION_JSON)
                                    .content(restoreBody))
                    .andExpect(status().isServiceUnavailable())
                    .andExpect(jsonPath("$.code").value("INTAKE_AGENT_UNAVAILABLE"))
                    .andExpect(jsonPath("$.callEvidence").doesNotExist());
            assertThat(requests.get()).isEqualTo(2);
            assertThat(
                            jdbc.queryForObject(
                                    "select retention_state from customer_intake where id = ?",
                                    String.class,
                                    intakeId))
                    .isEqualTo("ARCHIVED");
            assertThat(
                            jdbc.queryForObject(
                                    "select count(*) from customer_intake_restore_request where intake_id = ? and request_key = ?",
                                    Integer.class,
                                    intakeId,
                                    requestKey))
                    .isZero();
            assertThat(
                            jdbc.queryForObject(
                                    "select to_regclass('intake_model_call')::text", String.class))
                    .as(
                            "consumed calls need independently committed evidence even when restore rolls back")
                    .isEqualTo("intake_model_call");
            List<JsonNode> failedCalls = restoreEvidence(jdbc, intakeId, requestKey);
            assertThat(failedCalls).hasSize(1);
            assertKnownUsage(failedCalls.getFirst());
            assertThat(failedCalls.getFirst().path("failureClassification").asText()).isEmpty();
            assertThat(
                            jdbc.queryForObject(
                                    "select spring_failure_reason from intake_model_call where intake_id = ? and operation = 'RESTORE' and request_key = ? and status = 'FAILED'",
                                    String.class,
                                    intakeId,
                                    requestKey))
                    .isEqualTo("SERVICE_VALIDATION");

            mvc.perform(
                            post("/api/customer/v2/intakes/{id}/restore", intakeId)
                                    .principal(customer)
                                    .header("Idempotency-Key", requestKey)
                                    .contentType(MediaType.APPLICATION_JSON)
                                    .content(restoreBody))
                    .andExpect(status().isCreated())
                    .andExpect(jsonPath("$.retentionState").value("ACTIVE"));
            mvc.perform(
                            post("/api/customer/v2/intakes/{id}/restore", intakeId)
                                    .principal(customer)
                                    .header("Idempotency-Key", requestKey)
                                    .contentType(MediaType.APPLICATION_JSON)
                                    .content(restoreBody))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.intake.replayed").value(true));
            assertThat(requests.get()).isEqualTo(3);
            List<JsonNode> calls = restoreEvidence(jdbc, intakeId, requestKey);
            assertThat(calls).hasSize(2).allSatisfy(this::assertKnownUsage);
            assertThat(
                            calls.stream()
                                    .map(
                                            call ->
                                                    call.path("attempts")
                                                            .get(0)
                                                            .path("attemptId")
                                                            .asText())
                                    .distinct())
                    .hasSize(2);
            assertThat(
                            jdbc.queryForObject(
                                    "select count(*) from customer_intake_restore_request where intake_id = ? and request_key = ?",
                                    Integer.class,
                                    intakeId,
                                    requestKey))
                    .isEqualTo(1);
        } finally {
            server.stop(0);
        }
    }

    private List<JsonNode> restoreEvidence(JdbcTemplate jdbc, UUID intakeId, String requestKey) {
        return jdbc.query(
                "select evidence::text from intake_model_call where intake_id = ? and operation = 'RESTORE' and request_key = ? order by started_at, invocation_id",
                (rs, row) -> json.readTree(rs.getString(1)),
                intakeId,
                requestKey);
    }

    private void assertKnownUsage(JsonNode evidence) {
        assertThat(evidence.path("providerAttempts").asInt()).isEqualTo(1);
        assertThat(evidence.path("tokens").asInt()).isEqualTo(150);
        assertThat(evidence.path("costMicros").asInt()).isEqualTo(8);
        assertThat(evidence.path("currency").asText()).isEqualTo("USD");
        assertThat(evidence.path("usageComplete").asBoolean()).isTrue();
    }

    private String agentResponse(int call) {
        String intent = call == 2 ? "CONFIRM" : "UNDERSTANDING";
        String status = call == 2 ? "CONFIRMED" : "READY_TO_CONFIRM";
        return """
                {"intake_understanding":{
                  "intent":"%s","status":"%s","candidate_order_reference":"%s",
                  "issues":[{"kind":"LOGISTICS_DELAY","summary":"物流延迟"}],
                  "pending_issue_kinds":[],"remaining_order_references":[],"assistant_message":"请确认物流问题"
                },"intake_call_evidence":{
                  "schemaVersion":"intake-call-evidence-v1","currency":"USD",
                  "logicalCalls":1,"providerAttempts":1,"inputTokens":120,"outputTokens":30,
                  "tokens":150,"costMicros":8,"usageComplete":true,"failureClassification":"",
                  "attempts":[{"internalCallId":"db-call-%d","attemptId":"db-attempt-%d",
                    "attemptNumber":1,"provider":"deepseek","providerHttpStatus":200,
                    "inputTokens":120,"outputTokens":30,"totalTokens":150}]
                }}
                """
                .formatted(intent, status, ORDER, call, call);
    }
}
