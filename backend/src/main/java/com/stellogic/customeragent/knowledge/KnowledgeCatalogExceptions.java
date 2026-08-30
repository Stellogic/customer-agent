package com.stellogic.customeragent.knowledge;

final class KnowledgeAccessDeniedException extends RuntimeException {}

final class KnowledgeArticleNotFoundException extends RuntimeException {}

final class KnowledgeInvalidQueryException extends RuntimeException {
    KnowledgeInvalidQueryException(String message) {
        super(message);
    }
}

final class KnowledgeCatalogValidationException extends RuntimeException {
    private final String code;

    KnowledgeCatalogValidationException(String code, String message) {
        super(message);
        this.code = code;
    }

    String code() {
        return code;
    }
}

final class KnowledgeIndexUnavailableException extends RuntimeException {
    private final KnowledgeIndexState state;

    KnowledgeIndexUnavailableException(KnowledgeIndexState state) {
        super("knowledge index is not ready");
        this.state = state;
    }

    KnowledgeIndexState state() {
        return state;
    }
}
