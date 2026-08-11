package com.stellogic.customeragent.identity;

import java.net.URI;
import java.util.List;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Profile("local-demo")
@RequestMapping("/api/demo")
public final class SyntheticIdentityController {
    public static final String SESSION_COOKIE = "synthetic-demo-session";

    @GetMapping("/identities")
    public List<SyntheticIdentity> identities() {
        List<SyntheticIdentity> identities = new java.util.ArrayList<>(List.of(
                new SyntheticIdentity("customer-demo", "CUSTOMER", "客户演示入口"),
                new SyntheticIdentity("customer-other-demo", "CUSTOMER", "另一客户授权边界入口"),
                new SyntheticIdentity("support-demo", "SUPPORT", "客服演示入口"),
                new SyntheticIdentity("agent-machine", "AGENT", "受限 Agent 机器身份"),
                new SyntheticIdentity("executor-machine", "COMPENSATION_EXECUTOR", "受限补偿执行器机器身份")));
        SyntheticApprovers.entries().stream()
                .map(entry -> new SyntheticIdentity(entry.id(), "APPROVER", entry.label()))
                .forEach(identities::add);
        return List.copyOf(identities);
    }

    @GetMapping("/enter/support")
    public ResponseEntity<Void> enterSupport() {
        ResponseCookie cookie = ResponseCookie.from(SESSION_COOKIE, "support-demo")
                .httpOnly(true)
                .sameSite("Strict")
                .path("/")
                .build();
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(URI.create("/support"))
                .header(HttpHeaders.SET_COOKIE, cookie.toString())
                .build();
    }

    @GetMapping("/enter/approver/{approverId}")
    public ResponseEntity<Void> enterApprover(@PathVariable String approverId) {
        if (!SyntheticApprovers.contains(approverId)) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
        }
        ResponseCookie cookie = ResponseCookie.from(SESSION_COOKIE, approverId)
                .httpOnly(true)
                .sameSite("Strict")
                .path("/")
                .build();
        return ResponseEntity.status(HttpStatus.FOUND)
                .location(URI.create("/approver"))
                .header(HttpHeaders.SET_COOKIE, cookie.toString())
                .build();
    }

    @GetMapping("/session")
    public ResponseEntity<SyntheticIdentity> session(
            @CookieValue(value = SESSION_COOKIE, required = false) String sessionId) {
        if ("support-demo".equals(sessionId)) {
            return ResponseEntity.ok(new SyntheticIdentity("support-demo", "SUPPORT", "客服演示入口"));
        }
        return SyntheticApprovers.entries().stream()
                .filter(entry -> entry.id().equals(sessionId))
                .findFirst()
                .<ResponseEntity<SyntheticIdentity>>map(entry -> ResponseEntity.ok(
                        new SyntheticIdentity(entry.id(), "APPROVER", entry.label())))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.UNAUTHORIZED).build());
    }

    public record SyntheticIdentity(String id, String role, String label) {}
}
