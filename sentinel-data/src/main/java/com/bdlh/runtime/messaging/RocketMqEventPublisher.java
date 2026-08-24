package com.bdlh.runtime.messaging;

import com.bdlh.runtime.messaging.OutboxDtos.OutboxEvent;
import org.apache.rocketmq.client.apis.ClientConfiguration;
import org.apache.rocketmq.client.apis.ClientServiceProvider;
import org.apache.rocketmq.client.apis.message.Message;
import org.apache.rocketmq.client.apis.producer.Producer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import jakarta.annotation.PreDestroy;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** gRPC RocketMQ producer; publication happens only after an Outbox row was committed. */
@Component
public class RocketMqEventPublisher {

    private final boolean enabled;
    private final String endpoints;
    private final ClientServiceProvider provider;
    private final Map<String, Producer> producers = new ConcurrentHashMap<>();

    public RocketMqEventPublisher(
            @Value("${bdlh_runtime.rocketmq.enabled:false}") boolean enabled,
            @Value("${bdlh_runtime.rocketmq.endpoints:rmq-broker:8081}") String endpoints) {
        this.enabled = enabled;
        this.endpoints = endpoints;
        this.provider = enabled ? ClientServiceProvider.loadService() : null;
    }

    public boolean enabled() {
        return enabled;
    }

    public void publish(OutboxEvent event, byte[] envelope) throws Exception {
        if (!enabled) {
            throw new IllegalStateException("RocketMQ publisher is disabled");
        }
        Producer producer = producers.computeIfAbsent(event.topic(), this::createProducer);
        Message message = provider.newMessageBuilder()
                .setTopic(event.topic())
                .setTag(event.eventType())
                .setKeys(event.eventId().toString())
                .setBody(envelope)
                .build();
        producer.send(message);
    }

    private Producer createProducer(String topic) {
        try {
            ClientConfiguration config = ClientConfiguration.newBuilder()
                    .setEndpoints(endpoints)
                    .enableSsl(false)
                    .build();
            return provider.newProducerBuilder()
                    .setClientConfiguration(config)
                    .setTopics(topic)
                    .build();
        } catch (Exception exception) {
            throw new IllegalStateException("RocketMQ producer initialization failed", exception);
        }
    }

    @PreDestroy
    void close() {
        producers.values().forEach(producer -> {
            try {
                producer.close();
            } catch (Exception ignored) {
                // Shutdown must continue closing the Data Plane.
            }
        });
    }
}
