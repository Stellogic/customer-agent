package com.stellogic.customeragent.stream;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

public final class AuthorizedSsePollingStream {
    public static final long MAX_AUTHORIZATION_STALENESS_MILLIS = 60_000L;
    private static final ConcurrentHashMap<String, AtomicBoolean> SESSION_AUTHORITIES =
            new ConcurrentHashMap<>();

    private AuthorizedSsePollingStream() {}

    public static <E> Source<E> requireCurrentHttpSession(
            HttpServletRequest request, String expectedSubject, Source<E> delegate) {
        HttpSession session = request.getSession(false);
        if (session == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "session expired");
        }
        AtomicBoolean sessionAuthority = sessionAuthority(session);
        String boundSubject = sessionSubject(session);
        if (!Objects.equals(expectedSubject, boundSubject)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "session subject changed");
        }
        return new Source<>() {
            @Override
            public List<E> events(String afterCursor) {
                requireCurrentSession();
                return delegate.events(afterCursor);
            }

            @Override
            public void authorize() {
                requireCurrentSession();
                delegate.authorize();
            }

            @Override
            public String cursor(E event) {
                return delegate.cursor(event);
            }

            @Override
            public SseEmitter.SseEventBuilder render(E event) {
                return delegate.render(event);
            }

            private void requireCurrentSession() {
                if (!sessionAuthority.get()
                        || !Objects.equals(expectedSubject, sessionSubject(session))) {
                    throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "session expired");
                }
            }
        };
    }

    public static void invalidateHttpSession(HttpSession session) {
        invalidateHttpSessionId(session.getId());
    }

    public static void invalidateHttpSessionId(String sessionId) {
        AtomicBoolean active = SESSION_AUTHORITIES.remove(sessionId);
        if (active != null) {
            active.set(false);
        }
    }

    public static void rotateHttpSession(HttpSession session) {
        invalidateHttpSession(session);
        SESSION_AUTHORITIES.put(session.getId(), new AtomicBoolean(true));
    }

    private static AtomicBoolean sessionAuthority(HttpSession session) {
        return SESSION_AUTHORITIES.computeIfAbsent(
                session.getId(), ignored -> new AtomicBoolean(true));
    }

    private static String sessionSubject(HttpSession session) {
        try {
            Object value =
                    session.getAttribute(
                            HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY);
            if (value instanceof SecurityContext context && context.getAuthentication() != null) {
                return context.getAuthentication().getName();
            }
            return null;
        } catch (IllegalStateException expired) {
            return null;
        }
    }

    public static <E> SseEmitter open(
            String threadName,
            long pollIntervalMillis,
            long timeoutMillis,
            String initialCursor,
            Source<E> source) {
        List<E> replay = source.events(initialCursor);
        SseEmitter emitter = new SseEmitter(timeoutMillis);
        try {
            for (E event : replay) sendAuthorized(emitter, source, event);
            source.authorize();
            emitter.send(SseEmitter.event().comment("connected"));
        } catch (Exception exception) {
            emitter.completeWithError(exception);
            return emitter;
        }
        String nextCursor = replay.isEmpty() ? initialCursor : source.cursor(replay.getLast());
        startPolling(emitter, threadName, pollIntervalMillis, nextCursor, source);
        return emitter;
    }

    private static <E> void startPolling(
            SseEmitter emitter,
            String threadName,
            long intervalMillis,
            String initialCursor,
            Source<E> source) {
        AtomicBoolean closed = new AtomicBoolean();
        emitter.onCompletion(() -> closed.set(true));
        emitter.onTimeout(
                () -> {
                    closed.set(true);
                    emitter.complete();
                });
        emitter.onError(error -> closed.set(true));
        Thread.ofVirtual()
                .name(threadName)
                .start(
                        () -> {
                            String cursor = initialCursor;
                            try {
                                while (!closed.get()) {
                                    Thread.sleep(intervalMillis);
                                    List<E> incremental = source.events(cursor);
                                    source.authorize();
                                    for (E event : incremental) {
                                        sendAuthorized(emitter, source, event);
                                        cursor = source.cursor(event);
                                    }
                                }
                            } catch (InterruptedException exception) {
                                Thread.currentThread().interrupt();
                                emitter.complete();
                            } catch (Exception exception) {
                                emitter.completeWithError(exception);
                            }
                        });
    }

    private static <E> void sendAuthorized(SseEmitter emitter, Source<E> source, E event)
            throws java.io.IOException {
        source.authorize();
        emitter.send(source.render(event));
    }

    public interface Source<E> {
        List<E> events(String afterCursor);

        void authorize();

        String cursor(E event);

        SseEmitter.SseEventBuilder render(E event);
    }
}
