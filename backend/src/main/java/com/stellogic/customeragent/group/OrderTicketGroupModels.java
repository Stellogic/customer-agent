package com.stellogic.customeragent.group;

import java.util.List;
import java.util.UUID;

record CustomerOrderTicketGroup(
        String orderReference,
        List<OrderTicketSummary> tickets,
        List<PendingCustomerItem> pendingCustomerItems) {}

record OrderTicketSummary(
        UUID ticketId,
        String issueKind,
        String lifecycleState,
        String handlingMode,
        String controlledProgress,
        boolean pendingCustomerAction,
        boolean compensationFlowExists) {}

record PendingCustomerItem(UUID ticketId, String type, String customerQuestion) {}
