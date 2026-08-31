package com.stellogic.customeragent.queue;

import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import com.stellogic.customeragent.knowledge.AgentKnowledgeRetrievalAdapter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** 外层无事务：慢检索/生成之后重新进入客服授权边界，不执行业务动作。 */
@Service
class SupportAssistanceService {
    private final SupportAssistanceRequests requests;
    private final SupportAssistanceContext context;
    private final AgentKnowledgeRetrievalAdapter knowledge;
    private final SupportAssistanceGateway gateway;
    private final ObjectMapper json;

    SupportAssistanceService(SupportAssistanceRequests requests, SupportAssistanceContext context,
            AgentKnowledgeRetrievalAdapter knowledge, SupportAssistanceGateway gateway, ObjectMapper json) {
        this.requests = requests;
        this.context = context;
        this.knowledge = knowledge;
        this.gateway = gateway;
        this.json = json;
    }

    JsonNode request(String supportId, UUID ticketId, SupportAssistanceRequest request) {
        var receipt = requests.begin(supportId, ticketId, request);
        if (!receipt.execute()) return result(supportId, ticketId, request.requestId());
        AgentKnowledgeResult retrieved;
        try {
            retrieved = knowledge.searchSupport(supportId, request.query());
        } catch (RuntimeException failure) {
            // 原知识异常继续交其现有handler处理，尤其403不能降为无匹配。
            saveFailure(supportId, receipt, "RETRIEVAL_UNAVAILABLE", json.createObjectNode());
            throw failure;
        }
        context.requireAssignment(supportId, ticketId, request.assignmentId());
        JsonNode generated;
        try {
            generated = gateway.generate(request.kind(), request.query(), receipt.input(), retrieved);
        } catch (RuntimeException failure) {
            requests.recordModelAudit(supportId, request.requestId(),
                    "{\"status\":\"TRANSPORT_UNCONFIRMED\",\"attempts\":null}");
            saveFailure(supportId, receipt, "MODEL_UNAVAILABLE", json.createObjectNode());
            return result(supportId, ticketId, request.requestId());
        }
        requests.recordModelAudit(supportId, request.requestId(), json.writeValueAsString(generated.path("audit")));
        if (!"completed".equals(generated.path("status").asString())) {
            String code = "INVALID_ANSWER_FORMAT".equals(generated.path("code").asString())
                    ? "INVALID_ANSWER_FORMAT" : "MODEL_UNAVAILABLE";
            saveFailure(supportId, receipt, code, generated.path("audit"));
            return result(supportId, ticketId, request.requestId());
        }
        JsonNode stored;
        try {
            stored = project(receipt, generated.path("answer"), retrieved, generated.path("audit"));
        } catch (RuntimeException failure) {
            saveFailure(supportId, receipt, "INVALID_ANSWER_FORMAT", generated.path("audit"));
            return result(supportId, ticketId, request.requestId());
        }
        try {
            knowledge.revalidateSupport(supportId, json.treeToValue(stored.path("knowledge"), AgentKnowledgeResult.class));
        } catch (RuntimeException failure) {
            saveFailure(supportId, receipt, "RETRIEVAL_UNAVAILABLE", generated.path("audit"));
            throw failure;
        }
        requests.finish(supportId, ticketId, request.requestId(), json.writeValueAsString(stored), false);
        return result(supportId, ticketId, request.requestId());
    }

    JsonNode result(String supportId, UUID ticketId, UUID requestId) {
        var receipt = requests.read(supportId, ticketId, requestId);
        if (receipt.resultJson() == null) return envelope(receipt, Map.of("status", "loading", "kind", receipt.kind().name()));
        JsonNode stored = json.readTree(receipt.resultJson());
        if (stored.has("knowledge")) {
            knowledge.revalidateSupport(supportId, json.treeToValue(stored.path("knowledge"), AgentKnowledgeResult.class));
        }
        context.requireAssignment(supportId, ticketId, receipt.assignmentId());
        return envelope(receipt, stored.path("view"));
    }

    private JsonNode project(SupportAssistanceReceipt receipt, JsonNode raw,
            AgentKnowledgeResult retrieved, JsonNode audit) {
        if (!raw.isObject() || raw.size() != 4 || !raw.has("decision") || !raw.has("text")
                || !raw.has("followUp") || !raw.has("citations")) throw new IllegalArgumentException("invalid schema");
        var answer = json.treeToValue(raw, SupportAssistanceAnswer.class);
        if (answer == null || !List.of("SUPPORTED", "INSUFFICIENT_INFORMATION").contains(answer.decision())
                || answer.text() == null || answer.text().isBlank() || answer.text().length() > 2000
                || answer.followUp() != null && answer.followUp().length() > 500
                || answer.citations() == null || answer.citations().size() > 5) {
            throw new IllegalArgumentException("invalid assistance answer");
        }
        List<AgentKnowledgeResult.Source> selected = new ArrayList<>();
        List<JsonNode> citations = new ArrayList<>();
        int total = 0;
        for (var quote : answer.citations()) {
            var source = retrieved.results().stream().filter(item -> item.chunkId().equals(quote.chunkId()))
                    .findFirst().orElseThrow(() -> new IllegalArgumentException("citation is outside this request"));
            if (quote.quote() == null || quote.quote().isBlank() || !source.snippet().contains(quote.quote())) {
                throw new IllegalArgumentException("citation is not canonical");
            }
            total += quote.quote().length();
            selected.add(source);
            var citation = json.valueToTree(source).deepCopy();
            // 浏览器只收9个受控metadata字段；snippet为已核实逐字引文。
            ((tools.jackson.databind.node.ObjectNode) citation).put("snippet", quote.quote());
            citations.add(citation);
        }
        if (total > 4000) throw new IllegalArgumentException("quotation total limit");
        var view = json.createObjectNode();
        view.put("kind", receipt.kind().name()).put("requestId", receipt.requestId().toString());
        if ("INSUFFICIENT_INFORMATION".equals(answer.decision())) {
            view.put("status", "insufficient").put("explanation", answer.text());
            view.set("followUp", json.valueToTree(answer.followUp()));
        } else {
            view.put("status", "ready").put("text", answer.text());
            view.set("suggestions", json.valueToTree(List.of()));
            view.set("citations", json.valueToTree(citations));
        }
        return json.valueToTree(Map.of("view", view, "knowledge",
                new AgentKnowledgeResult(retrieved.schema(), retrieved.indexGeneration(), selected), "audit", audit));
    }

    private void saveFailure(String supportId, SupportAssistanceReceipt receipt, String code, JsonNode audit) {
        String reason = switch (code) {
            case "INVALID_ANSWER_FORMAT" -> "format";
            case "RETRIEVAL_UNAVAILABLE" -> "retrieval";
            default -> "model";
        };
        requests.finish(supportId, receipt.ticketId(), receipt.requestId(), json.writeValueAsString(
                Map.of("view", Map.of("status", "error", "reason", reason), "audit", audit)), true);
    }

    private JsonNode envelope(SupportAssistanceReceipt receipt, Object view) {
        return json.valueToTree(Map.of("schema", "support-assistance-v1", "ticketId", receipt.ticketId(),
                "assignmentId", receipt.assignmentId(), "requestId", receipt.requestId(),
                "kind", receipt.kind().name(), "view", view));
    }
}
