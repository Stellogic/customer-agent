package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.investigation.AutoResolutionService;
import java.time.Instant;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/customer/tickets")
public final class CustomerAutoResolutionController {
    private final AutoResolutionService service;

    public CustomerAutoResolutionController(AutoResolutionService service) {
        this.service = service;
    }

    @PostMapping("/{ticketId}/auto-resolution/cancel")
    ResponseEntity<Void> cancel(
            Authentication authentication,
            @PathVariable UUID ticketId,
            @RequestBody CancelRequest request) {
        if (request.candidateDueAt() == null || request.candidateGeneration() < 1) {
            throw new InvalidCustomerRequestException("缺少待取消的自动解决截止时间或版本");
        }
        service.cancel(
                authentication.getName(),
                ticketId,
                request.candidateDueAt(),
                request.candidateGeneration());
        return ResponseEntity.noContent().build();
    }

    record CancelRequest(Instant candidateDueAt, long candidateGeneration) {}
}
