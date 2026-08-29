package com.stellogic.customeragent.ticket;

import java.util.UUID;

enum AgentReplyStreamEventType {
    LOADING,
    PROGRESS,
    STREAM_STARTED,
    CONTENT_DELTA,
    COMPLETED,
    ABORTED,
    FAILED
}

record AgentReplyStreamCommand(
        UUID ticketId,
        UUID generationId,
        String requestId,
        AgentReplyStreamEventType type,
        Integer chunkIndex,
        String delta,
        String stage) {}

record AgentReplyStreamResult(boolean replayed) {}

record CurrentReplyStream(String status, String body, String progressStage) {}
