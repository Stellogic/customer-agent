package com.stellogic.customeragent.identity;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/capabilities")
public final class MachineIdentityController {
    private final byte[] agentToken;
    private final byte[] executorToken;

    public MachineIdentityController(
            @Value("${baseline.identity.agent-token}") String agentToken,
            @Value("${baseline.identity.executor-token}") String executorToken) {
        this.agentToken = agentToken.getBytes(StandardCharsets.UTF_8);
        this.executorToken = executorToken.getBytes(StandardCharsets.UTF_8);
    }

    @GetMapping("/agent/probe")
    public Map<String, String> agent(@RequestHeader(HttpHeaders.AUTHORIZATION) String authorization) {
        require(authorization, agentToken);
        return Map.of("identity", "agent", "capability", "ticket-investigation-probe");
    }

    @GetMapping("/executor/probe")
    public Map<String, String> executor(@RequestHeader(HttpHeaders.AUTHORIZATION) String authorization) {
        require(authorization, executorToken);
        return Map.of("identity", "compensation-executor", "capability", "compensation-execution-probe");
    }

    private static void require(String authorization, byte[] expected) {
        byte[] actual = authorization.startsWith("Bearer ")
                ? authorization.substring(7).getBytes(StandardCharsets.UTF_8)
                : new byte[0];
        if (!MessageDigest.isEqual(actual, expected)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "machine identity cannot use this capability");
        }
    }
}

