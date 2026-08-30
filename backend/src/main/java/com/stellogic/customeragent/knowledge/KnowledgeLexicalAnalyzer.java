package com.stellogic.customeragent.knowledge;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;
import org.apache.lucene.analysis.cjk.CJKAnalyzer;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;

/** 文档与问题使用同一 CJK 双字分析器，PostgreSQL 仍负责候选匹配和排名。 */
final class KnowledgeLexicalAnalyzer {
    private KnowledgeLexicalAnalyzer() {}

    static String document(String text) {
        return String.join(" ", terms(text));
    }

    static String query(String text) {
        return terms(text).stream()
                .distinct()
                .map(term -> "'" + term.replace("\\", "\\\\").replace("'", "''") + "'")
                .collect(Collectors.joining(" | "));
    }

    static List<String> terms(String text) {
        try (var analyzer = new CJKAnalyzer();
                var stream = analyzer.tokenStream("knowledge", text)) {
            var term = stream.addAttribute(CharTermAttribute.class);
            List<String> result = new ArrayList<>();
            stream.reset();
            while (stream.incrementToken()) result.add(term.toString());
            stream.end();
            return result;
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }
}
