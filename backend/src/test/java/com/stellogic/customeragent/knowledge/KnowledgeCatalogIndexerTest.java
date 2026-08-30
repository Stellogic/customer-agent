package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class KnowledgeCatalogIndexerTest {
    @Test
    void failedRebuildKeepsPreviousReadyOrEmptyCatalogSearchable() {
        assertThat(
                        KnowledgeCatalogIndexer.retainCatalogStatusAfterFailure(
                                state(KnowledgeIndexStatus.READY, 3)))
                .isEqualTo(KnowledgeIndexStatus.READY);
        assertThat(
                        KnowledgeCatalogIndexer.retainCatalogStatusAfterFailure(
                                state(KnowledgeIndexStatus.EMPTY, 2)))
                .isEqualTo(KnowledgeIndexStatus.EMPTY);
        assertThat(
                        KnowledgeCatalogIndexer.retainCatalogStatusAfterFailure(
                                state(KnowledgeIndexStatus.EMPTY, 0)))
                .isEqualTo(KnowledgeIndexStatus.FAILED);
        assertThat(
                        KnowledgeCatalogIndexer.retainCatalogStatusAfterFailure(
                                state(KnowledgeIndexStatus.FAILED, 1)))
                .isEqualTo(KnowledgeIndexStatus.FAILED);
    }

    private static KnowledgeIndexState state(KnowledgeIndexStatus status, long generation) {
        return new KnowledgeIndexState(
                status,
                generation,
                null,
                null,
                java.time.Instant.parse("2026-08-28T00:00:00Z"),
                1,
                1,
                null,
                null);
    }
}
