package com.stellogic.customeragent.ticket;

import com.stellogic.customeragent.investigation.CustomerReplySafetyPolicy;
import com.stellogic.customeragent.reliability.StableParameterDigest;
import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
class JdbcAgentReplyStreamService implements AgentReplyStreamService {
    private static final String EPOCH = "customer-public-v1";
    private final JdbcTemplate jdbc;
    private final TicketAuthorityLock authorityLock;
    private final Clock clock;

    JdbcAgentReplyStreamService(JdbcTemplate jdbc, TicketAuthorityLock authorityLock, Clock clock) {
        this.jdbc = jdbc;
        this.authorityLock = authorityLock;
        this.clock = clock;
    }

    @Override
    @Transactional
    public AgentReplyStreamResult append(AgentReplyStreamCommand command) {
        authorityLock.acquire(command.ticketId());
        String digest =
                StableParameterDigest.sha256(
                        command.type().name(),
                        String.valueOf(command.chunkIndex()),
                        String.valueOf(command.delta()),
                        String.valueOf(command.stage()));
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                (ResultSetExtractor<Void>) resultSet -> null,
                command.generationId() + "\n" + command.requestId());
        List<String> replay =
                jdbc.query(
                        "select parameter_digest from agent_public_reply_event_request where generation_id = ? and request_id = ?",
                        (rs, row) -> rs.getString(1),
                        command.generationId(),
                        command.requestId());
        if (!replay.isEmpty()) {
            if (!digest.equals(replay.getFirst())) {
                throw new ResponseStatusException(
                        HttpStatus.CONFLICT,
                        "stream request identity reused with different fields");
            }
            return new AgentReplyStreamResult(true);
        }

        GenerationAuthority authority = requireCurrentGeneration(command);
        Instant now = clock.instant();
        Timestamp at = Timestamp.from(now);
        CurrentState state = currentState(command);
        String productEvent;
        switch (command.type()) {
            case LOADING -> {
                requireState(state, null, "LOADING");
                upsert(command, "LOADING", "", 0, "UNDERSTANDING", at);
                productEvent = "AGENT_REPLY_LOADING";
            }
            case PROGRESS -> {
                if (state != null && isTerminal(state.status())) rejectTransition();
                upsert(
                        command,
                        state == null ? "LOADING" : state.status(),
                        state == null ? "" : state.body(),
                        state == null ? 0 : state.nextChunkIndex(),
                        command.stage(),
                        at);
                productEvent = "PUBLIC_PROGRESS_UPDATED";
            }
            case STREAM_STARTED -> {
                if (state != null && isTerminal(state.status())) rejectTransition();
                upsert(
                        command,
                        "STREAMING",
                        state == null ? "" : state.body(),
                        state == null ? 0 : state.nextChunkIndex(),
                        state == null ? "COMPOSING_REPLY" : state.progressStage(),
                        at);
                productEvent = "AGENT_REPLY_STREAM_STARTED";
            }
            case CONTENT_DELTA -> {
                if (state == null
                        || !"STREAMING".equals(state.status())
                        || state.nextChunkIndex() != command.chunkIndex()) {
                    rejectTransition();
                }
                String body = state.body() + command.delta();
                if (body.length() > 1_000) {
                    throw new ResponseStatusException(
                            HttpStatus.UNPROCESSABLE_ENTITY, "public reply exceeds safe limit");
                }
                if (!CustomerReplySafetyPolicy.isAuthorizedBodyPrefix(
                        body, authority.orderReference(), false)) {
                    throw new ResponseStatusException(
                            HttpStatus.UNPROCESSABLE_ENTITY,
                            "public reply is outside the Spring-authorized narrative");
                }
                upsert(
                        command,
                        "STREAMING",
                        body,
                        state.nextChunkIndex() + 1,
                        state.progressStage(),
                        at);
                productEvent = "AGENT_REPLY_CONTENT_DELTA";
            }
            case COMPLETED -> {
                if (state == null
                        || !"STREAMING".equals(state.status())
                        || !CustomerReplySafetyPolicy.isAuthorizedBodyPrefix(
                                state.body(), authority.orderReference(), true)) {
                    rejectTransition();
                }
                upsert(
                        command,
                        "COMPLETED",
                        state.body(),
                        state.nextChunkIndex(),
                        state.progressStage(),
                        at);
                productEvent = "AGENT_REPLY_COMPLETED";
            }
            case ABORTED -> {
                if (state != null && isTerminal(state.status())) rejectTransition();
                upsert(command, "ABORTED", "", 0, null, at);
                productEvent = "AGENT_REPLY_ABORTED";
            }
            case FAILED -> {
                if (state != null && isTerminal(state.status())) rejectTransition();
                upsert(command, "FAILED", "", 0, null, at);
                productEvent = "AGENT_REPLY_FAILED";
            }
            default -> throw new IllegalStateException("unhandled public reply event");
        }

        Long sequence =
                jdbc.queryForObject(
                        "select coalesce(max(sequence), 0) + 1 from customer_public_event where ticket_id = ? and epoch = ?",
                        Long.class,
                        command.ticketId(),
                        EPOCH);
        jdbc.update(
                "insert into customer_public_event (ticket_id, epoch, sequence, agent_generation, event_type, payload, occurred_at) "
                        + "values (?, ?, ?, ?, ?, "
                        + payloadExpression(command.type())
                        + ", ?)",
                eventArguments(command, authority.generationNumber(), sequence, productEvent, at));
        jdbc.update(
                "insert into agent_public_reply_event_request (generation_id, request_id, parameter_digest, received_at) values (?, ?, ?, ?)",
                command.generationId(),
                command.requestId(),
                digest,
                at);
        return new AgentReplyStreamResult(false);
    }

    private GenerationAuthority requireCurrentGeneration(AgentReplyStreamCommand command) {
        List<GenerationAuthority> rows =
                jdbc.query(
                        "select g.generation_number, t.order_reference from agent_processing_generation g "
                                + "join support_ticket t on t.id = g.ticket_id "
                                + "where g.id = ? and g.ticket_id = ? and g.status = ? "
                                + "and g.generation_number = (select max(g2.generation_number) from agent_processing_generation g2 where g2.ticket_id = g.ticket_id) "
                                + "and t.handling_mode = 'AGENT' and not t.customer_human_preference",
                        (rs, row) -> new GenerationAuthority(rs.getLong(1), rs.getString(2)),
                        command.generationId(),
                        command.ticketId(),
                        command.type() == AgentReplyStreamEventType.COMPLETED
                                ? "COMPLETED"
                                : "ACTIVE");
        if (rows.isEmpty()) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "generation cannot publish customer content");
        }
        return rows.getFirst();
    }

    private CurrentState currentState(AgentReplyStreamCommand command) {
        List<CurrentState> rows =
                jdbc.query(
                        "select status, body, next_chunk_index, progress_stage from agent_public_reply_stream where generation_id = ? for update",
                        (rs, row) ->
                                new CurrentState(
                                        rs.getString(1),
                                        rs.getString(2),
                                        rs.getInt(3),
                                        rs.getString(4)),
                        command.generationId());
        return rows.isEmpty() ? null : rows.getFirst();
    }

    private void upsert(
            AgentReplyStreamCommand command,
            String status,
            String body,
            int nextChunkIndex,
            String progressStage,
            Timestamp at) {
        jdbc.update(
                "insert into agent_public_reply_stream (generation_id, ticket_id, status, body, next_chunk_index, progress_stage, updated_at) "
                        + "values (?, ?, ?, ?, ?, ?, ?) on conflict (generation_id) do update set "
                        + "status = excluded.status, body = excluded.body, next_chunk_index = excluded.next_chunk_index, "
                        + "progress_stage = excluded.progress_stage, updated_at = excluded.updated_at",
                command.generationId(),
                command.ticketId(),
                status,
                body,
                nextChunkIndex,
                progressStage,
                at);
    }

    private static String payloadExpression(AgentReplyStreamEventType type) {
        return switch (type) {
            case CONTENT_DELTA -> "jsonb_build_object('chunkIndex', ?::integer, 'delta', ?::text)";
            case PROGRESS -> "jsonb_build_object('stage', ?::text)";
            case LOADING -> "jsonb_build_object('status', 'LOADING')";
            case STREAM_STARTED -> "jsonb_build_object('status', 'STREAMING')";
            case COMPLETED -> "jsonb_build_object('status', 'COMPLETED')";
            case ABORTED -> "jsonb_build_object('status', 'ABORTED')";
            case FAILED -> "jsonb_build_object('status', 'FAILED')";
        };
    }

    private static Object[] eventArguments(
            AgentReplyStreamCommand command,
            long generationNumber,
            Long sequence,
            String eventType,
            Timestamp at) {
        java.util.ArrayList<Object> values =
                new java.util.ArrayList<>(
                        List.of(command.ticketId(), EPOCH, sequence, generationNumber, eventType));
        if (command.type() == AgentReplyStreamEventType.CONTENT_DELTA) {
            values.add(command.chunkIndex());
            values.add(command.delta());
        } else if (command.type() == AgentReplyStreamEventType.PROGRESS) {
            values.add(command.stage());
        }
        values.add(at);
        return values.toArray();
    }

    private static void requireState(CurrentState state, String allowed, String alsoAllowed) {
        if (state != null
                && !java.util.Objects.equals(state.status(), allowed)
                && !java.util.Objects.equals(state.status(), alsoAllowed)) {
            rejectTransition();
        }
    }

    private static boolean isTerminal(String status) {
        return SetHolder.TERMINAL.contains(status);
    }

    private static void rejectTransition() {
        throw new ResponseStatusException(HttpStatus.CONFLICT, "invalid public reply transition");
    }

    private record GenerationAuthority(long generationNumber, String orderReference) {}

    private record CurrentState(
            String status, String body, int nextChunkIndex, String progressStage) {}

    private static final class SetHolder {
        private static final java.util.Set<String> TERMINAL =
                java.util.Set.of("COMPLETED", "ABORTED", "FAILED");

        private SetHolder() {}
    }
}
