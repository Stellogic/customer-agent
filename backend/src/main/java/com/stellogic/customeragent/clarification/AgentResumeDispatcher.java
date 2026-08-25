package com.stellogic.customeragent.clarification;

import java.time.Duration;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Component
@ConditionalOnProperty(name = "baseline.migrate-only", havingValue = "false", matchIfMissing = true)
class AgentResumeDispatcher {
    private final AgentResumeStore store;
    private final RestClient agent;
    private final ObjectMapper json;

    AgentResumeDispatcher(
            AgentResumeStore store,
            @Value("${baseline.agent.base-url}") String baseUrl,
            @Value("${baseline.agent.token}") String token,
            ObjectMapper json) {
        this.store = store;
        this.json = json;
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(3));
        factory.setReadTimeout(Duration.ofSeconds(5));
        this.agent =
                RestClient.builder()
                        .baseUrl(baseUrl)
                        .defaultHeader("Authorization", "Bearer " + token)
                        .requestFactory(factory)
                        .build();
    }

    @Scheduled(fixedDelayString = "${baseline.agent.resume-poll-delay:250}")
    void dispatchNext() {
        store.claim().ifPresent(this::dispatch);
    }

    private void dispatch(AgentResumeStore.PendingResume resume) {
        try {
            ExistingRun existing = findRun(resume);
            if (existing != null) {
                store.submitted(resume.resumeRequestId(), existing.runId());
                return;
            }
            String body =
                    agent.post()
                            .uri("/threads/{threadId}/runs", resume.threadId())
                            .contentType(MediaType.APPLICATION_JSON)
                            .body(
                                    Map.of(
                                            "assistant_id",
                                            "baseline_agent",
                                            "if_not_exists",
                                            "reject",
                                            "metadata",
                                            Map.of(
                                                    "resume_request_id",
                                                            resume.resumeRequestId().toString(),
                                                    "generation_id",
                                                            resume.generationId().toString(),
                                                    "clarification_request_id",
                                                            resume.clarificationRequestId()
                                                                    .toString()),
                                            "command",
                                            Map.of(
                                                    "resume",
                                                    Map.of(
                                                            "clarificationRequestId",
                                                            resume.clarificationRequestId()
                                                                    .toString()))))
                            .retrieve()
                            .body(String.class);
            JsonNode response = json.readTree(body == null ? "{}" : body);
            store.submitted(resume.resumeRequestId(), response.path("run_id").asText(null));
        } catch (RuntimeException exception) {
            store.retry(resume.resumeRequestId(), exception.getMessage());
        }
    }

    private ExistingRun findRun(AgentResumeStore.PendingResume resume) {
        String body =
                agent.get()
                        .uri(
                                "/threads/{threadId}/runs?limit=100&select=metadata&select=run_id",
                                resume.threadId())
                        .retrieve()
                        .body(String.class);
        try {
            for (JsonNode run : json.readTree(body == null ? "[]" : body)) {
                if (resume.resumeRequestId()
                        .toString()
                        .equals(run.path("metadata").path("resume_request_id").asText())) {
                    return new ExistingRun(run.path("run_id").asText(null));
                }
            }
            return null;
        } catch (RuntimeException exception) {
            throw new IllegalStateException("invalid resume reconciliation response", exception);
        }
    }

    private record ExistingRun(String runId) {}
}
