package com.stellogic.customeragent.stream;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

public final class AuthorizedSsePollingStream {
    private AuthorizedSsePollingStream() {}

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
