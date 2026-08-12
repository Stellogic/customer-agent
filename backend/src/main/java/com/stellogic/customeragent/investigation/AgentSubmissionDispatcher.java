package com.stellogic.customeragent.investigation;

import java.time.Duration;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
@ConditionalOnProperty(name = "baseline.migrate-only", havingValue = "false", matchIfMissing = true)
class AgentSubmissionDispatcher {
    private final AgentSubmissionStore store;
    private final RestClient agent;
    private final ObjectMapper json;

    AgentSubmissionDispatcher(
            AgentSubmissionStore store,
            @Value("${baseline.agent.base-url}") String baseUrl,
            @Value("${baseline.agent.token}") String token,
            ObjectMapper json) {
        this.store = store;
        this.json = json;
        var requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(3));
        requestFactory.setReadTimeout(Duration.ofSeconds(5));
        this.agent =
                RestClient.builder()
                        .baseUrl(baseUrl)
                        .defaultHeader("Authorization", "Bearer " + token)
                        .requestFactory(requestFactory)
                        .build();
    }

    @Scheduled(fixedDelayString = "${baseline.agent.submission-poll-delay:250}")
    void dispatchNext() {
        store.claim().ifPresent(this::dispatch);
    }

    private void dispatch(AgentSubmissionStore.PendingSubmission submission) {
        try {
            ensureThread(submission);
            ensureRun(submission);
            store.submitted(submission.submissionRequestId());
        } catch (RuntimeException exception) {
            store.retry(submission.submissionRequestId(), exception.getMessage());
        }
    }

    private void ensureThread(AgentSubmissionStore.PendingSubmission submission) {
        if (exists("/threads/{threadId}", submission.threadId())) return;
        int status =
                agent.post()
                        .uri("/threads")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(
                                Map.of(
                                        "thread_id", submission.threadId().toString(),
                                        "if_exists", "do_nothing",
                                        "metadata",
                                                Map.of(
                                                        "generation_id",
                                                                submission
                                                                        .generationId()
                                                                        .toString(),
                                                        "ticket_id",
                                                                submission.ticketId().toString())))
                        .exchange((request, response) -> response.getStatusCode().value());
        requireSuccess(status, "thread submission");
    }

    private void ensureRun(AgentSubmissionStore.PendingSubmission submission) {
        if (hasLiveOrSuccessfulSubmissionRun(submission)) return;
        int status =
                agent.post()
                        .uri("/threads/{threadId}/runs", submission.threadId())
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(
                                Map.of(
                                        "assistant_id",
                                        "baseline_agent",
                                        "if_not_exists",
                                        "reject",
                                        "metadata",
                                        Map.of(
                                                "submission_request_id",
                                                        submission.submissionRequestId().toString(),
                                                "generation_id",
                                                        submission.generationId().toString()),
                                        "input",
                                        Map.of(
                                                "requested_by", "spring",
                                                "ticket_id", submission.ticketId().toString(),
                                                "generation_id",
                                                        submission.generationId().toString())))
                        .exchange((request, response) -> response.getStatusCode().value());
        requireSuccess(status, "run submission");
    }

    private boolean hasLiveOrSuccessfulSubmissionRun(
            AgentSubmissionStore.PendingSubmission submission) {
        String runs =
                agent.get()
                        .uri(
                                "/threads/{threadId}/runs?limit=100&select=metadata&select=run_id&select=status",
                                submission.threadId())
                        .retrieve()
                        .body(String.class);
        if (runs == null) return false;
        try {
            JsonNode response = json.readTree(runs);
            for (JsonNode run : response) {
                if (submission
                                .submissionRequestId()
                                .toString()
                                .equals(run.path("metadata").path("submission_request_id").asText())
                        && !isTerminalFailure(run.path("status").asText())) {
                    return true;
                }
            }
            return false;
        } catch (RuntimeException exception) {
            throw new IllegalStateException("invalid run reconciliation response", exception);
        }
    }

    private static boolean isTerminalFailure(String status) {
        return Set.of("error", "failed", "cancelled", "canceled", "timeout")
                .contains(status.toLowerCase(Locale.ROOT));
    }

    private boolean exists(String uri, Object... variables) {
        int status =
                agent.get()
                        .uri(uri, variables)
                        .exchange((request, response) -> response.getStatusCode().value());
        if (status == 404) return false;
        requireSuccess(status, "submission reconciliation");
        return true;
    }

    private static void requireSuccess(int status, String operation) {
        if (!HttpStatusCode.valueOf(status).is2xxSuccessful()) {
            throw new IllegalStateException(operation + " returned HTTP " + status);
        }
    }
}
