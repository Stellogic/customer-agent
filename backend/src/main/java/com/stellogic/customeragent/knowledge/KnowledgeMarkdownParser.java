package com.stellogic.customeragent.knowledge;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.core.io.Resource;

final class KnowledgeMarkdownParser {
    private static final Set<String> REQUIRED_FIELDS =
            Set.of("id", "title", "version", "updated_at", "applicability", "status", "current");
    private static final Pattern ARTICLE_ID = Pattern.compile("[a-z0-9][a-z0-9-]{2,63}");
    private static final Pattern METADATA_KEY = Pattern.compile("[a-z][a-z0-9_]*");

    KnowledgeArticleDocument parse(Resource resource) throws IOException {
        String sourceFile = sourceFile(resource);
        String source = readNormalized(resource);
        String[] lines = source.split("\\n", -1);
        if (lines.length < 3 || !"---".equals(lines[0])) {
            throw invalid(sourceFile, 1, "文件必须以 YAML 风格元数据边界开始");
        }

        int closingBoundary = -1;
        Map<String, String> metadata = new LinkedHashMap<>();
        for (int index = 1; index < lines.length; index++) {
            String line = lines[index];
            if ("---".equals(line)) {
                closingBoundary = index;
                break;
            }
            if (line.isBlank()) {
                throw invalid(sourceFile, index + 1, "元数据区域不允许空行");
            }
            int separator = line.indexOf(':');
            if (separator < 1 || !METADATA_KEY.matcher(line.substring(0, separator).trim()).matches()) {
                throw invalid(sourceFile, index + 1, "元数据必须使用 key: value 格式");
            }
            String key = line.substring(0, separator).trim();
            String value = line.substring(separator + 1).trim();
            if (!REQUIRED_FIELDS.contains(key)) {
                throw invalid(sourceFile, index + 1, "不支持的元数据字段: " + key);
            }
            if (metadata.putIfAbsent(key, value) != null) {
                throw invalid(sourceFile, index + 1, "重复元数据字段: " + key);
            }
        }
        if (closingBoundary < 0) {
            throw invalid(sourceFile, lines.length, "缺少元数据结束边界");
        }
        Set<String> missing = new HashSet<>(REQUIRED_FIELDS);
        missing.removeAll(metadata.keySet());
        if (!missing.isEmpty()) {
            throw invalid(sourceFile, 1, "缺少必需元数据: " + missing.stream().sorted().toList());
        }

        String articleId = scalar(metadata, "id", sourceFile);
        if (!ARTICLE_ID.matcher(articleId).matches()) {
            throw invalid(sourceFile, 1, "id 必须是稳定的小写短标识");
        }
        String title = boundedScalar(metadata, "title", sourceFile, 200);
        String version = boundedScalar(metadata, "version", sourceFile, 64);
        Instant updatedAt = instant(metadata.get("updated_at"), sourceFile, "updated_at");
        List<String> applicability = applicability(metadata.get("applicability"), sourceFile);
        KnowledgePublicationStatus status = publicationStatus(metadata.get("status"), sourceFile);
        boolean current = booleanValue(metadata.get("current"), sourceFile, "current");
        if (current && status != KnowledgePublicationStatus.PUBLISHED) {
            throw invalid(sourceFile, 1, "current 条目必须是 PUBLISHED");
        }

        List<String> bodyLines =
                Arrays.stream(lines, closingBoundary + 1, lines.length).toList();
        String body = String.join("\n", bodyLines).trim();
        if (body.isBlank()) {
            throw invalid(sourceFile, closingBoundary + 1, "正文不能为空");
        }
        List<KnowledgeChunkDocument> chunks =
                KnowledgeChunker.chunk(
                        articleId, version, sourceFile, bodyLines, closingBoundary + 2);
        if (chunks.isEmpty()) {
            throw invalid(sourceFile, closingBoundary + 1, "正文无法形成知识分段");
        }
        String immutableContent =
                articleId
                        + "\u0000"
                        + title
                        + "\u0000"
                        + version
                        + "\u0000"
                        + updatedAt
                        + "\u0000"
                        + String.join(",", applicability)
                        + "\u0000"
                        + body;
        return new KnowledgeArticleDocument(
                articleId,
                title,
                version,
                updatedAt,
                applicability,
                status,
                current,
                sourceFile,
                KnowledgeDigests.sha256(immutableContent),
                body,
                chunks);
    }

    private static String readNormalized(Resource resource) throws IOException {
        try (InputStream input = resource.getInputStream()) {
            String source = new String(input.readAllBytes(), StandardCharsets.UTF_8);
            if (!source.isEmpty() && source.charAt(0) == '\ufeff') source = source.substring(1);
            return source.replace("\r\n", "\n").replace('\r', '\n');
        }
    }

    private static String sourceFile(Resource resource) {
        String filename = resource.getFilename();
        if (filename == null || filename.isBlank() || !filename.endsWith(".md")) {
            throw new KnowledgeCatalogValidationException(
                    "INVALID_KNOWLEDGE_SOURCE", "知识源必须是带 .md 扩展名的文件");
        }
        return "knowledge/" + filename;
    }

    private static String scalar(Map<String, String> metadata, String key, String sourceFile) {
        String value = unquote(metadata.get(key));
        if (value.isBlank()) throw invalid(sourceFile, 1, key + " 不能为空");
        return value;
    }

    private static String boundedScalar(
            Map<String, String> metadata, String key, String sourceFile, int maxLength) {
        String value = scalar(metadata, key, sourceFile);
        if (value.length() > maxLength) throw invalid(sourceFile, 1, key + " 超出长度限制");
        return value;
    }

    private static Instant instant(String value, String sourceFile, String key) {
        try {
            return Instant.parse(unquote(value));
        } catch (DateTimeParseException exception) {
            throw invalid(sourceFile, 1, key + " 必须是 ISO-8601 时间");
        }
    }

    private static List<String> applicability(String value, String sourceFile) {
        String list = unquote(value);
        if (!list.startsWith("[") || !list.endsWith("]")) {
            throw invalid(sourceFile, 1, "applicability 必须是 [SCOPE, ...] 列表");
        }
        String content = list.substring(1, list.length() - 1).trim();
        if (content.isBlank()) throw invalid(sourceFile, 1, "applicability 不能为空");
        List<String> values = new ArrayList<>();
        for (String item : content.split(",", -1)) {
            String scope = unquote(item.trim()).toUpperCase(Locale.ROOT);
            if (!Set.of("CUSTOMER", "INTERNAL", "SUPPORT", "APPROVER").contains(scope)) {
                throw invalid(sourceFile, 1, "不支持的适用范围: " + scope);
            }
            if (values.contains(scope)) {
                throw invalid(sourceFile, 1, "重复适用范围: " + scope);
            }
            values.add(scope);
        }
        return List.copyOf(values);
    }

    private static KnowledgePublicationStatus publicationStatus(String value, String sourceFile) {
        try {
            return KnowledgePublicationStatus.valueOf(unquote(value).toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException exception) {
            throw invalid(sourceFile, 1, "status 必须是 DRAFT、PUBLISHED 或 RETIRED");
        }
    }

    private static boolean booleanValue(String value, String sourceFile, String key) {
        String normalized = unquote(value).toLowerCase(Locale.ROOT);
        if ("true".equals(normalized)) return true;
        if ("false".equals(normalized)) return false;
        throw invalid(sourceFile, 1, key + " 必须是 true 或 false");
    }

    private static String unquote(String value) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.length() >= 2
                && ((normalized.startsWith("\"") && normalized.endsWith("\""))
                        || (normalized.startsWith("'") && normalized.endsWith("'")))) {
            return normalized.substring(1, normalized.length() - 1).trim();
        }
        return normalized;
    }

    private static KnowledgeCatalogValidationException invalid(
            String sourceFile, int line, String message) {
        return new KnowledgeCatalogValidationException(
                "INVALID_KNOWLEDGE_ARTICLE", sourceFile + ":" + line + " " + message);
    }

}
