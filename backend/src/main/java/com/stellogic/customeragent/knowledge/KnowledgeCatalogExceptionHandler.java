package com.stellogic.customeragent.knowledge;

import java.util.Map;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public final class KnowledgeCatalogExceptionHandler {
    @ExceptionHandler(KnowledgeAccessDeniedException.class)
    ResponseEntity<Map<String, String>> forbidden() {
        return ResponseEntity.status(HttpStatus.FORBIDDEN)
                .cacheControl(CacheControl.noStore())
                .body(Map.of("code", "KNOWLEDGE_ACCESS_DENIED", "message", "当前身份无权访问知识目录"));
    }

    @ExceptionHandler(KnowledgeArticleNotFoundException.class)
    ResponseEntity<Map<String, String>> notFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .cacheControl(CacheControl.noStore())
                .body(Map.of("code", "KNOWLEDGE_ARTICLE_NOT_FOUND", "message", "知识条目不存在"));
    }

    @ExceptionHandler(KnowledgeInvalidQueryException.class)
    ResponseEntity<Map<String, String>> invalid(KnowledgeInvalidQueryException exception) {
        return ResponseEntity.badRequest()
                .cacheControl(CacheControl.noStore())
                .body(Map.of("code", "INVALID_KNOWLEDGE_QUERY", "message", exception.getMessage()));
    }

    @ExceptionHandler(KnowledgeIndexUnavailableException.class)
    ResponseEntity<KnowledgeError> unavailable(KnowledgeIndexUnavailableException exception) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .cacheControl(CacheControl.noStore())
                .body(
                        new KnowledgeError(
                                "KNOWLEDGE_INDEX_UNAVAILABLE",
                                "知识索引当前不可用，请稍后重试",
                                exception.state()));
    }

    record KnowledgeError(String code, String message, KnowledgeIndexState index) {}
}
