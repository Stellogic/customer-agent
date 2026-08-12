package com.stellogic.customeragent.status;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTimeoutPreemptively;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class AgentAvailabilityProbeTest {

    @Test
    void probeRejectsAnUnboundedConnectTimeout() {
        assertThrows(
                IllegalArgumentException.class,
                () ->
                        StatusConfiguration.agentProbe(
                                "http://127.0.0.1:1",
                                "test-token",
                                Duration.ZERO,
                                Duration.ofMillis(100)));
    }

    @Test
    void probeRejectsAnUnboundedReadTimeout() {
        assertThrows(
                IllegalArgumentException.class,
                () ->
                        StatusConfiguration.agentProbe(
                                "http://127.0.0.1:1",
                                "test-token",
                                Duration.ofMillis(100),
                                Duration.ZERO));
    }

    @Test
    void statusDegradesWithinTheConfiguredReadTimeoutWhenAgentAcceptsButDoesNotRespond()
            throws Exception {
        try (ServerSocket agent = new ServerSocket(0)) {
            Semaphore released = new Semaphore(0);
            Thread.ofVirtual()
                    .start(
                            () ->
                                    acceptHangingConnections(
                                            agent,
                                            1,
                                            released,
                                            new AtomicInteger(),
                                            new AtomicInteger()));

            var probe =
                    StatusConfiguration.agentProbe(
                            "http://127.0.0.1:" + agent.getLocalPort(),
                            "test-token",
                            Duration.ofMillis(100),
                            Duration.ofMillis(100));
            MockMvc mvc =
                    MockMvcBuilders.standaloneSetup(
                                    new SystemStatusController(
                                            new SystemStatusService(() -> true, probe)))
                            .build();

            assertTimeoutPreemptively(
                    Duration.ofSeconds(2),
                    () -> {
                        mvc.perform(get("/api/system/status"))
                                .andExpect(status().isOk())
                                .andExpect(jsonPath("$.status").value("DEGRADED"))
                                .andExpect(jsonPath("$.services.database").value("UP"))
                                .andExpect(jsonPath("$.services.agent").value("DOWN"));
                        assertTrue(released.tryAcquire(1, TimeUnit.SECONDS));
                    });
        }
    }

    @Test
    void statusDegradesWithinTheConfiguredBoundaryWhenAgentRefusesTheConnection() throws Exception {
        int unavailablePort;
        try (ServerSocket reservedPort = new ServerSocket(0)) {
            unavailablePort = reservedPort.getLocalPort();
        }
        MockMvc mvc = statusApi("http://127.0.0.1:" + unavailablePort, Duration.ofMillis(100));

        assertTimeoutPreemptively(
                Duration.ofSeconds(2),
                () ->
                        mvc.perform(get("/api/system/status"))
                                .andExpect(status().isOk())
                                .andExpect(jsonPath("$.status").value("DEGRADED"))
                                .andExpect(jsonPath("$.services.database").value("UP"))
                                .andExpect(jsonPath("$.services.agent").value("DOWN")));
    }

    @Test
    void statusRemainsUpWhenAgentRespondsSuccessfully() throws Exception {
        try (ServerSocket agent = new ServerSocket(0)) {
            Thread.ofVirtual().start(() -> respondSuccessfully(agent));
            MockMvc mvc =
                    statusApi("http://127.0.0.1:" + agent.getLocalPort(), Duration.ofMillis(250));

            mvc.perform(get("/api/system/status"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.status").value("UP"))
                    .andExpect(jsonPath("$.services.spring").value("UP"))
                    .andExpect(jsonPath("$.services.database").value("UP"))
                    .andExpect(jsonPath("$.services.agent").value("UP"));
        }
    }

    @Test
    void repeatedHangingResponsesReleaseEachConnectionAfterTheReadTimeout() throws Exception {
        int requestCount = 6;
        try (ServerSocket agent = new ServerSocket(0)) {
            Semaphore released = new Semaphore(0);
            AtomicInteger active = new AtomicInteger();
            AtomicInteger maximumActive = new AtomicInteger();
            Thread.ofVirtual()
                    .start(
                            () ->
                                    acceptHangingConnections(
                                            agent, requestCount, released, active, maximumActive));
            MockMvc mvc =
                    statusApi("http://127.0.0.1:" + agent.getLocalPort(), Duration.ofMillis(75));

            assertTimeoutPreemptively(
                    Duration.ofSeconds(3),
                    () -> {
                        for (int request = 0; request < requestCount; request++) {
                            mvc.perform(get("/api/system/status"))
                                    .andExpect(status().isOk())
                                    .andExpect(jsonPath("$.services.agent").value("DOWN"));
                            assertTrue(released.tryAcquire(1, TimeUnit.SECONDS));
                        }
                        assertTrue(maximumActive.get() <= 1);
                    });
        }
    }

    private static MockMvc statusApi(String agentBaseUrl, Duration readTimeout) {
        var probe =
                StatusConfiguration.agentProbe(
                        agentBaseUrl, "test-token", Duration.ofMillis(100), readTimeout);
        return MockMvcBuilders.standaloneSetup(
                        new SystemStatusController(new SystemStatusService(() -> true, probe)))
                .build();
    }

    private static void respondSuccessfully(ServerSocket server) {
        try (Socket connection = server.accept()) {
            connection.getInputStream().readNBytes(1);
            byte[] response =
                    "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
                            .getBytes(StandardCharsets.US_ASCII);
            connection.getOutputStream().write(response);
        } catch (IOException ignored) {
            // The test owns and closes the server socket.
        }
    }

    private static void acceptHangingConnections(
            ServerSocket server,
            int connectionCount,
            Semaphore released,
            AtomicInteger active,
            AtomicInteger maximumActive) {
        try {
            for (int accepted = 0; accepted < connectionCount; accepted++) {
                Socket connection = server.accept();
                Thread.ofVirtual()
                        .start(
                                () -> {
                                    try (connection) {
                                        int current = active.incrementAndGet();
                                        maximumActive.accumulateAndGet(current, Math::max);
                                        while (connection.getInputStream().read() != -1) {
                                            // Consume the request, but deliberately send no
                                            // response.
                                        }
                                    } catch (IOException ignored) {
                                        // A read timeout closes the client side of this connection.
                                    } finally {
                                        active.decrementAndGet();
                                        released.release();
                                    }
                                });
            }
        } catch (IOException ignored) {
            // The test owns and closes the server socket.
        }
    }
}
