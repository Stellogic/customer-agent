package com.stellogic.customeragent.group;

import java.util.List;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/customer/v2/order-ticket-groups")
public final class OrderTicketGroupController {
    static final String SCHEMA = "customer-order-ticket-groups-v1";
    private final OrderTicketGroupService service;

    OrderTicketGroupController(OrderTicketGroupService service) {
        this.service = service;
    }

    @GetMapping
    ResponseEntity<Response> groups(Authentication authentication) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(
                        new Response(
                                "CUSTOMER_ORDER_TICKET_GROUPS",
                                SCHEMA,
                                service.customerGroups(authentication.getName())));
    }

    record Response(String view, String schema, List<CustomerOrderTicketGroup> groups) {}
}
