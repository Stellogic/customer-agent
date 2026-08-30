package com.stellogic.customeragent.knowledge;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

final class KnowledgeDigests {
    private KnowledgeDigests() {}

    static String sha256(String value) {
        try {
            return java.util.HexFormat.of()
                    .formatHex(
                            MessageDigest.getInstance("SHA-256")
                                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }
}
