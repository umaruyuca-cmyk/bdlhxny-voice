package com.bdlh.runtime.messaging;

import com.bdlh.runtime.messaging.OutboxDtos.OutboxEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Runs inside the sole Java Data Plane JVM; it is not a separate Worker process. */
@Component
public class OutboxRelay {

    private final TaskOutboxService outboxService;
    private final RocketMqEventPublisher publisher;
    private final ObjectMapper objectMapper;
    private final int batchSize;

    public OutboxRelay(
            TaskOutboxService outboxService,
            RocketMqEventPublisher publisher,
            ObjectMapper objectMapper,
            @Value("${bdlh_runtime.rocketmq.relay-batch-size:50}") int batchSize) {
        this.outboxService = outboxService;
        this.publisher = publisher;
        this.objectMapper = objectMapper;
        this.batchSize = Math.min(Math.max(batchSize, 1), 100);
    }

    @Scheduled(fixedDelayString = "${bdlh_runtime.rocketmq.relay-fixed-delay-ms:1000}")
    public void relayPendingEvents() {
        if (!publisher.enabled()) {
            return;
        }
        OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
        List<OutboxEvent> events = outboxService.claimReadyEvents(batchSize, now, now.minusMinutes(5));
        for (OutboxEvent event : events) {
            try {
                publisher.publish(event, objectMapper.writeValueAsBytes(envelope(event)));
                outboxService.markPublished(event.eventId(), event.claimToken(), OffsetDateTime.now(ZoneOffset.UTC));
            } catch (Exception exception) {
                outboxService.markPublishFailed(
                        event.eventId(), event.claimToken(), exception.getClass().getSimpleName(),
                        OffsetDateTime.now(ZoneOffset.UTC));
            }
        }
    }

    private Map<String, Object> envelope(OutboxEvent event) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("event_id", event.eventId());
        result.put("event_type", event.eventType());
        result.put("schema_version", event.schemaVersion());
        result.put("aggregate_type", event.aggregateType());
        result.put("aggregate_id", event.aggregateId());
        result.put("aggregate_version", event.aggregateVersion());
        result.put("occurred_at", event.createdAt());
        result.put("producer", "bdlh-runtime-data");
        result.put("trace_id", event.traceId());
        result.put("correlation_id", event.correlationId());
        result.put("authenticated_user_id", event.authenticatedUserId());
        result.put("payload", event.payload());
        return result;
    }
}
