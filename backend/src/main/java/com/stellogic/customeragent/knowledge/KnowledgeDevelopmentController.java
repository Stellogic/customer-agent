package com.stellogic.customeragent.knowledge;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** 仅隔离开发栈可开启的候选采集面；不返回被判为可回答的产品结果。 */
@RestController
@Profile("knowledge-development")
@ConditionalOnProperty(name = "baseline.knowledge.development-probe-enabled", havingValue = "true")
final class KnowledgeDevelopmentController {
    private final KnowledgeRetrievalService service;

    KnowledgeDevelopmentController(KnowledgeRetrievalService service) {
        this.service = service;
    }

    @GetMapping("/api/internal/knowledge/development-candidates")
    ResponseEntity<KnowledgeDevelopmentResponse> candidates(
            Authentication authentication,
            @RequestParam("q") String query,
            @RequestParam(value = "scope", required = false) String scope) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.developmentCandidates(authentication.getName(), query, scope));
    }
}
