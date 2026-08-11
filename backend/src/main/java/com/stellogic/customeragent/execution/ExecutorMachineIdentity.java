package com.stellogic.customeragent.execution;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
final class ExecutorMachineIdentity {
    private final byte[] token;

    ExecutorMachineIdentity(@Value("${baseline.identity.executor-token}") String token) {
        this.token = token.getBytes(StandardCharsets.UTF_8);
    }

    void require(String authorization) {
        byte[] actual = authorization != null && authorization.startsWith("Bearer ")
                ? authorization.substring(7).getBytes(StandardCharsets.UTF_8)
                : new byte[0];
        if (!MessageDigest.isEqual(actual, token)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "executor identity required");
        }
    }
}
