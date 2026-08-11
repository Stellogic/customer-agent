package com.stellogic.customeragent.closure;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

public interface ClosureService {
    CustomerReplyResult reply(CustomerReplyCommand command);

    List<UUID> dueTicketIds(Instant now);

    void closeIfDue(UUID ticketId, Instant now);
}
