package com.stellogic.customeragent.knowledge;

import java.util.ArrayList;
import java.util.List;

final class KnowledgeChunker {
    private static final int MAX_CHUNK_CHARACTERS = 800;

    private KnowledgeChunker() {}

    static List<KnowledgeChunkDocument> chunk(
            String articleId,
            String version,
            String sourceFile,
            List<String> bodyLines,
            int bodyStartLine) {
        List<LineBlock> blocks = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        int startLine = -1;
        for (int index = 0; index < bodyLines.size(); index++) {
            String line = bodyLines.get(index);
            if (line.isBlank()) {
                addBlock(blocks, current, startLine, index, bodyStartLine);
                current.setLength(0);
                startLine = -1;
                continue;
            }
            if (startLine < 0) startLine = index + 1;
            if (current.length() > 0) current.append('\n');
            current.append(line.stripTrailing());
        }
        addBlock(blocks, current, startLine, bodyLines.size(), bodyStartLine);

        List<KnowledgeChunkDocument> chunks = new ArrayList<>();
        int ordinal = 1;
        for (LineBlock block : blocks) {
            for (String content : split(block.content())) {
                String chunkId =
                        "chunk-"
                                + KnowledgeDigests.sha256(
                                        articleId
                                                + "\u0000"
                                                + version
                                                + "\u0000"
                                                + sourceFile
                                                + "\u0000"
                                                + ordinal
                                                + "\u0000"
                                                + block.startLine()
                                                + "\u0000"
                                                + block.endLine()
                                                + "\u0000"
                                                + content);
                chunks.add(
                        new KnowledgeChunkDocument(
                                chunkId,
                                articleId,
                                version,
                                ordinal++,
                                sourceFile,
                                block.startLine(),
                                block.endLine(),
                                content));
            }
        }
        return List.copyOf(chunks);
    }

    private static void addBlock(
            List<LineBlock> blocks,
            StringBuilder content,
            int start,
            int end,
            int bodyStartLine) {
        if (start >= 0 && !content.toString().isBlank()) {
            blocks.add(
                    new LineBlock(
                            bodyStartLine + start,
                            bodyStartLine + Math.max(start, end - 1),
                            content.toString().trim()));
        }
    }

    private static List<String> split(String content) {
        List<String> parts = new ArrayList<>();
        int offset = 0;
        while (offset < content.length()) {
            int end = Math.min(offset + MAX_CHUNK_CHARACTERS, content.length());
            if (end < content.length()) {
                int boundary = content.lastIndexOf(' ', end);
                if (boundary > offset + 120) end = boundary;
            }
            String part = content.substring(offset, end).trim();
            if (!part.isBlank()) parts.add(part);
            offset = end;
            while (offset < content.length() && Character.isWhitespace(content.charAt(offset))) offset++;
        }
        return parts;
    }

    private record LineBlock(int startLine, int endLine, String content) {}
}
