package com.stellogic.customeragent.knowledge;

import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
final class KnowledgeRetrievalController {
    private final KnowledgeRetrievalService service;

    KnowledgeRetrievalController(KnowledgeRetrievalService service) {
        this.service = service;
    }

    @GetMapping("/api/internal/knowledge/search")
    ResponseEntity<KnowledgeRetrievalResponse> search(
            Authentication authentication,
            @RequestParam("q") String query,
            @RequestParam(value = "scope", required = false) String scope) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.search(authentication.getName(), query, scope));
    }
}
