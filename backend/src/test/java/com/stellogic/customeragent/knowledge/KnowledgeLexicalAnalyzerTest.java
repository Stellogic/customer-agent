package com.stellogic.customeragent.knowledge;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class KnowledgeLexicalAnalyzerTest {
    @Test
    void continuousChineseQuestionAndDocumentShareTermsWithoutWholeSentenceMatch() {
        assertThat(KnowledgeLexicalAnalyzer.document("育苗温室保持适宜温度。"))
                .contains("温室", "温度");
        assertThat(KnowledgeLexicalAnalyzer.query("温室温度？"))
                .contains("'温室'", "'温度'", " | ")
                .doesNotContain(" & ");
    }

    @Test
    void mixedLatinWidthAndCaseAreNormalizedOnBothSides() {
        assertThat(KnowledgeLexicalAnalyzer.document("ＳＰＲＩＮＧ 2026"))
                .isEqualTo(KnowledgeLexicalAnalyzer.document("spring 2026"));
        assertThat(KnowledgeLexicalAnalyzer.query("？！")).isEmpty();
    }
}
