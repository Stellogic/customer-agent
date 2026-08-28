package com.stellogic.customeragent.ticket;

import java.util.List;
import java.util.UUID;

public interface CustomerTicketService {
    TicketCreationResult create(CreateCustomerTicket command);

    CustomerMessageResult appendMessage(AppendCustomerMessage command);

    UUID createFollowUp(
            String customerId,
            String requestId,
            String orderReference,
            String description,
            String issueKind,
            UUID originalTicketId);

    CustomerPublicSnapshot snapshot(String customerId, UUID ticketId);

    List<CustomerPublicEvent> events(String customerId, UUID ticketId, String afterCursor);
}
