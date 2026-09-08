package com.stellogic.customeragent.ticket;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.stellogic.customeragent.reliability.TicketAuthorityLock;
import java.sql.ResultSet;
import java.time.Clock;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.web.server.ResponseStatusException;

class JdbcAgentReplyStreamServiceTest {
    @Test
    void leadingWhitespaceCanBeFollowedByTextAndCompleted() throws Exception {
        var fixture = new StreamFixture();
        fixture.append(AgentReplyStreamEventType.CONTENT_DELTA, 0, " ");
        fixture.append(AgentReplyStreamEventType.CONTENT_DELTA, 1, "调查说明");
        fixture.append(AgentReplyStreamEventType.COMPLETED, null, null);
        assertThat(fixture.body).isEqualTo(" 调查说明");
        assertThat(fixture.status).isEqualTo("COMPLETED");
    }

    @Test
    void whitespaceOnlyCompleteBodyIsRejected() throws Exception {
        var fixture = new StreamFixture();
        fixture.append(AgentReplyStreamEventType.CONTENT_DELTA, 0, " ");
        assertThatThrownBy(() -> fixture.append(AgentReplyStreamEventType.COMPLETED, null, null))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("invalid public reply transition");
        assertThat(fixture.status).isEqualTo("STREAMING");
    }

    private static final class StreamFixture {
        private final UUID ticket = UUID.randomUUID();
        private final UUID generation = UUID.randomUUID();
        private String status = "STREAMING";
        private String body = "";
        private int chunkIndex;
        private final JdbcAgentReplyStreamService service;

        StreamFixture() {
            JdbcTemplate jdbc =
                    mock(
                            JdbcTemplate.class,
                            invocation -> {
                                String sql = invocation.getArgument(0);
                                if (invocation.getMethod().getName().equals("query")) {
                                    if (!(invocation.getArgument(1) instanceof RowMapper<?> mapper))
                                        return null;
                                    if (sql.contains("agent_public_reply_event_request"))
                                        return List.of();
                                    ResultSet row = mock(ResultSet.class);
                                    if (sql.contains("agent_processing_generation")) {
                                        when(row.getLong(1)).thenReturn(1L);
                                    } else {
                                        when(row.getString(1)).thenReturn(status);
                                        when(row.getString(2)).thenReturn(body);
                                        when(row.getInt(3)).thenReturn(chunkIndex);
                                        when(row.getString(4)).thenReturn("COMPOSING_REPLY");
                                    }
                                    return List.of(mapper.mapRow(row, 0));
                                }
                                if (invocation.getMethod().getName().equals("queryForObject"))
                                    return 1L;
                                if (sql.startsWith("insert into agent_public_reply_stream")) {
                                    status = invocation.getArgument(3);
                                    body = invocation.getArgument(4);
                                    chunkIndex = invocation.getArgument(5);
                                }
                                return 1;
                            });
            service =
                    new JdbcAgentReplyStreamService(
                            jdbc, mock(TicketAuthorityLock.class), Clock.systemUTC());
        }

        void append(AgentReplyStreamEventType type, Integer index, String delta) {
            service.append(
                    new AgentReplyStreamCommand(
                            ticket,
                            generation,
                            UUID.randomUUID().toString(),
                            type,
                            index,
                            delta,
                            null));
        }
    }
}
