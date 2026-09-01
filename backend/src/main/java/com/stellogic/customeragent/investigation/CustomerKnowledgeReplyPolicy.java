package com.stellogic.customeragent.investigation;

import com.stellogic.customeragent.knowledge.AgentKnowledgeResult;
import com.stellogic.customeragent.ticket.CustomerKnowledgeProjection;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** 接受边界校验；引文真实不等于语义充分，后者仍须真实回答质量验收。 */
final class CustomerKnowledgeReplyPolicy {
    private static final Pattern INSTRUCTION =
            Pattern.compile(
                    "(?i)(忽略.{0,12}(指令|规则|提示)|泄露|系统提示词|developer message|system"
                            + " message|ignore.{0,30}(instruction|rule|prompt)|api[_"
                            + " -]?key|bearer\\s|<\\|.*?\\|>)");

    private CustomerKnowledgeReplyPolicy() {}

    static CustomerKnowledgeProjection validate(
            CustomerKnowledgeReply reply, AgentKnowledgeResult receipt) {
        if (reply == null
                || reply.status() == null
                || reply.answer() == null
                || reply.answer().isBlank()
                || reply.answer().length() > 1500
                || reply.citations() == null
                || reply.citations().size() > 5
                || (reply.status() == CustomerKnowledgeStatus.SUPPORTED)
                        != !reply.citations().isEmpty()) {
            throw invalid("INVALID_KNOWLEDGE_CITATION");
        }
        if (INSTRUCTION.matcher(reply.answer()).find()
                || CustomerReplySafetyPolicy.unsafeKnowledgeBody(reply.answer())) {
            throw invalid("UNSAFE_KNOWLEDGE");
        }
        validatePublicText(reply.answer(), receipt);
        var projected = new ArrayList<CustomerKnowledgeProjection.Source>();
        Set<String> seen = new HashSet<>();
        for (CustomerKnowledgeCitation citation : reply.citations()) {
            AgentKnowledgeResult.Source source =
                    receipt.results().stream()
                            .filter(
                                    item ->
                                            item.articleId().equals(citation.articleId())
                                                    && item.version().equals(citation.version())
                                                    && item.chunkId().equals(citation.chunkId()))
                            .findFirst()
                            .orElseThrow(() -> invalid("INVALID_KNOWLEDGE_CITATION"));
            if (!source.applicability().contains("CUSTOMER_PUBLIC")
                    || citation.quote() == null
                    || citation.quote().isBlank()
                    || !source.snippet().contains(citation.quote())
                    || !seen.add(source.chunkId())) {
                throw invalid("INVALID_KNOWLEDGE_CITATION");
            }
            if (INSTRUCTION.matcher(source.snippet()).find()
                    || INSTRUCTION.matcher(source.title()).find()) {
                throw invalid("UNSAFE_KNOWLEDGE");
            }
            var value = new CustomerKnowledgeProjection.Source(source.title(), source.updatedAt());
            if (!projected.contains(value)) projected.add(value);
        }
        return new CustomerKnowledgeProjection(reply.status().name(), projected);
    }

    static void validatePublicText(String text, AgentKnowledgeResult receipt) {
        if (receipt.results().stream()
                .anyMatch(
                        source ->
                                text.contains(source.chunkId())
                                        || text.contains(source.articleId()))) {
            throw invalid("UNSAFE_KNOWLEDGE");
        }
    }

    private static ResponseStatusException invalid(String code) {
        return new Rejected(code);
    }

    static final class Rejected extends ResponseStatusException {
        Rejected(String code) {
            super(HttpStatus.UNPROCESSABLE_ENTITY, code);
        }
    }
}
