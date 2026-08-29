package com.stellogic.customeragent.knowledge;

import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/internal/knowledge")
public final class KnowledgeCatalogController {
    private final KnowledgeCatalogService service;

    KnowledgeCatalogController(KnowledgeCatalogService service) {
        this.service = service;
    }

    @GetMapping
    ResponseEntity<KnowledgeCatalogResponse> search(
            Authentication authentication,
            @RequestParam(value = "q", defaultValue = "") String query,
            @RequestParam(value = "limit", defaultValue = "20") int limit) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.search(authentication.getName(), query, limit));
    }

    @GetMapping("/index")
    ResponseEntity<KnowledgeIndexState> index(Authentication authentication) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.index(authentication.getName()));
    }

    @GetMapping("/articles/{articleId}")
    ResponseEntity<KnowledgeArticleResponse> article(
            Authentication authentication,
            @PathVariable String articleId,
            @RequestParam(value = "version", required = false) String version) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.article(authentication.getName(), articleId, version));
    }

    @PostMapping("/index/rebuild")
    ResponseEntity<KnowledgeIndexState> rebuild(Authentication authentication) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(service.rebuild(authentication.getName()));
    }
}
