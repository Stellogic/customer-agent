package com.stellogic.customeragent.ticket;

import java.util.List;
import java.util.UUID;

public interface CustomerTicketService {
    TicketCreationResult create(CreateCustomerTicket command);

    CustomerPublicSnapshot snapshot(String customerId, UUID ticketId);

    List<CustomerPublicEvent> events(String customerId, UUID ticketId, String afterCursor);
}
