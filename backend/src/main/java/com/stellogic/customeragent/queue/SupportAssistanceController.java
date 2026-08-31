package com.stellogic.customeragent.queue;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/support/workbench/tickets/{ticketId}/assistance")
final class SupportAssistanceController {
    private final SupportAssistanceContext context;
    private final SupportAssistanceService service;

    SupportAssistanceController(SupportAssistanceContext context, SupportAssistanceService service) {
        this.context = context;
        this.service = service;
    }

    @GetMapping("/context")
    ResponseEntity<?> context(Authentication principal, @PathVariable UUID ticketId, HttpServletRequest http) {
        var session = SessionBinding.capture(http, principal.getName());
        var authorized = context.load(principal.getName(), ticketId);
        session.verify();
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(Map.of(
                "schema", "support-assistance-v1", "ticketId", ticketId,
                "assignmentId", authorized.assignmentId()));
    }

    @PostMapping("/requests")
    ResponseEntity<JsonNode> request(Authentication principal, @PathVariable UUID ticketId,
            @RequestBody Map<String, Object> body, HttpServletRequest http) {
        var session = SessionBinding.capture(http, principal.getName());
        JsonNode response = service.request(principal.getName(), ticketId, parse(body));
        session.verify();
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(response);
    }

    @GetMapping("/requests/{requestId}")
    ResponseEntity<JsonNode> result(Authentication principal, @PathVariable UUID ticketId,
            @PathVariable UUID requestId, HttpServletRequest http) {
        var session = SessionBinding.capture(http, principal.getName());
        JsonNode response = service.result(principal.getName(), ticketId, requestId);
        session.verify();
        return ResponseEntity.ok().cacheControl(CacheControl.noStore())
                .body(response);
    }

    @ExceptionHandler(SupportAssistanceConflictException.class)
    ResponseEntity<?> conflict() {
        return ResponseEntity.status(HttpStatus.CONFLICT).cacheControl(CacheControl.noStore())
                .body(Map.of("code", "REQUEST_CONFLICT", "message", "请求标识已绑定其他辅助输入"));
    }

    private static SupportAssistanceRequest parse(Map<String, Object> body) {
        try {
            if (!body.keySet().equals(Set.of("schema", "assignmentId", "requestId", "kind", "query"))
                    || !"support-assistance-v1".equals(body.get("schema"))
                    || !(body.get("query") instanceof String query)
                    || query.isBlank() || query.length() > 200) throw new IllegalArgumentException();
            return new SupportAssistanceRequest(UUID.fromString((String) body.get("assignmentId")),
                    UUID.fromString((String) body.get("requestId")),
                    SupportAssistanceKind.valueOf((String) body.get("kind")), query.trim());
        } catch (IllegalArgumentException | ClassCastException | NullPointerException invalid) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "辅助请求格式无效");
        }
    }

    private record SessionBinding(HttpSession session, String id, String subject) {
        static SessionBinding capture(HttpServletRequest request, String subject) {
            HttpSession session = request.getSession(false);
            if (session == null) throw expired();
            var binding = new SessionBinding(session, session.getId(), subject);
            binding.verify();
            return binding;
        }

        void verify() {
            try {
                Object stored = session.getAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY);
                if (!id.equals(session.getId()) || !(stored instanceof SecurityContext security)
                        || security.getAuthentication() == null
                        || !subject.equals(security.getAuthentication().getName())) throw expired();
            } catch (IllegalStateException invalidated) {
                throw expired();
            }
        }

        private static ResponseStatusException expired() {
            return new ResponseStatusException(HttpStatus.UNAUTHORIZED, "辅助会话已失效");
        }
    }
}
