package com.bdlh.runtime.messaging;

import com.bdlh.runtime.messaging.MemoryCandidateService.MemoryCandidateRequest;
import com.bdlh.runtime.messaging.OutboxDtos.OutboxEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

class MemoryCandidateOutboxTest {

    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();

    @Test
    void enqueueRejectsL4Metadata() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        MemoryCandidateService service = new MemoryCandidateService(jdbc, objectMapper);
        ObjectNode metadata = objectMapper.createObjectNode();
        metadata.put("knowledge_type", "confirmed");
        metadata.put("risk_tolerance", "BALANCED");
        MemoryCandidateRequest request = new MemoryCandidateRequest(
                UUID.randomUUID(), "偏好简洁", metadata, "trace", "corr");

        assertThatThrownBy(() -> service.enqueue("7", request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("L4");
        verify(jdbc, never()).update(any(String.class), any(Object[].class));
    }

    @Test
    void relayPublishesClaimedMemoryEventsWhenRocketMqEnabled() {
        UUID eventId = UUID.randomUUID();
        UUID claim = UUID.randomUUID();
        OutboxEvent event = new OutboxEvent(
                eventId,
                MemoryCandidateService.TOPIC,
                MemoryCandidateService.EVENT_TYPE,
                1,
                "MEMORY_CANDIDATE",
                eventId.toString(),
                1,
                "7",
                objectMapper.createObjectNode().put("content", "偏好"),
                "trace",
                "corr",
                1,
                claim,
                OffsetDateTime.parse("2026-08-17T00:00:00Z"));
        FakeOutbox outbox = new FakeOutbox(List.of(event));
        RecordingPublisher publisher = new RecordingPublisher(true);

        OutboxRelay relay = new OutboxRelay(outbox, publisher, objectMapper, 10);
        relay.relayPendingEvents();

        assertThat(publisher.published).hasSize(1);
        assertThat(publisher.published.get(0).topic()).isEqualTo(MemoryCandidateService.TOPIC);
        assertThat(outbox.publishedCount.get()).isEqualTo(1);
    }

    @Test
    void relaySkipsWhenRocketMqDisabled() {
        FakeOutbox outbox = new FakeOutbox(List.of());
        RecordingPublisher publisher = new RecordingPublisher(false);

        OutboxRelay relay = new OutboxRelay(outbox, publisher, objectMapper, 10);
        relay.relayPendingEvents();

        assertThat(publisher.published).isEmpty();
        assertThat(outbox.claimCount.get()).isZero();
    }

    static final class FakeOutbox extends TaskOutboxService {
        private final List<OutboxEvent> ready;
        private final AtomicInteger claimCount = new AtomicInteger();
        private final AtomicInteger publishedCount = new AtomicInteger();

        FakeOutbox(List<OutboxEvent> ready) {
            super(mock(JdbcTemplate.class), new ObjectMapper());
            this.ready = ready;
        }

        @Override
        public List<OutboxEvent> claimReadyEvents(int requestedLimit, OffsetDateTime now, OffsetDateTime staleBefore) {
            claimCount.incrementAndGet();
            return List.copyOf(ready);
        }

        @Override
        public boolean markPublished(UUID eventId, UUID claimToken, OffsetDateTime publishedAt) {
            publishedCount.incrementAndGet();
            return true;
        }

        @Override
        public boolean markPublishFailed(UUID eventId, UUID claimToken, String error, OffsetDateTime now) {
            return true;
        }
    }

    static final class RecordingPublisher extends RocketMqEventPublisher {
        private final boolean on;
        private final List<OutboxEvent> published = new ArrayList<>();

        RecordingPublisher(boolean on) {
            super(false, "localhost:8081");
            this.on = on;
        }

        @Override
        public boolean enabled() {
            return on;
        }

        @Override
        public void publish(OutboxEvent event, byte[] envelope) {
            published.add(event);
        }
    }
}
