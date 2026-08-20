package com.bdlh.runtime.messaging;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.apache.rocketmq.client.apis.ClientConfiguration;
import org.apache.rocketmq.client.apis.ClientServiceProvider;
import org.apache.rocketmq.client.apis.consumer.ConsumeResult;
import org.apache.rocketmq.client.apis.consumer.FilterExpression;
import org.apache.rocketmq.client.apis.consumer.FilterExpressionType;
import org.apache.rocketmq.client.apis.consumer.PushConsumer;
import org.apache.rocketmq.client.apis.message.MessageView;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.ByteBuffer;
import java.util.Collections;
import java.util.UUID;

/** The notification consumer lives inside the existing Data Plane JVM. */
@Component
public class RocketMqNotificationConsumer {

    private final boolean enabled;
    private final String endpoints;
    private final NotificationProjectionService projectionService;
    private PushConsumer consumer;

    public RocketMqNotificationConsumer(
            @Value("${bdlh_runtime.rocketmq.enabled:false}") boolean enabled,
            @Value("${bdlh_runtime.rocketmq.endpoints:rmq-broker:8081}") String endpoints,
            NotificationProjectionService projectionService) {
        this.enabled = enabled;
        this.endpoints = endpoints;
        this.projectionService = projectionService;
    }

    @PostConstruct
    void start() throws Exception {
        if (!enabled) {
            return;
        }
        ClientServiceProvider provider = ClientServiceProvider.loadService();
        ClientConfiguration configuration = ClientConfiguration.newBuilder()
                .setEndpoints(endpoints)
                .enableSsl(false)
                .build();
        consumer = provider.newPushConsumerBuilder()
                .setClientConfiguration(configuration)
                .setConsumerGroup(NotificationProjectionService.CONSUMER_GROUP)
                .setSubscriptionExpressions(Collections.singletonMap(
                        TaskOutboxService.NOTIFICATION_TOPIC,
                        new FilterExpression("*", FilterExpressionType.TAG)))
                .setConsumptionThreadCount(1)
                .setMessageListener(this::consume)
                .build();
    }

    private ConsumeResult consume(MessageView message) {
        try {
            projectionService.project(eventId(message), bytes(message.getBody()));
            return ConsumeResult.SUCCESS;
        } catch (Exception exception) {
            return ConsumeResult.FAILURE;
        }
    }

    private static UUID eventId(MessageView message) {
        return message.getKeys().stream().findFirst()
                .map(UUID::fromString)
                .orElseThrow(() -> new IllegalArgumentException("event_id key is missing"));
    }

    private static byte[] bytes(ByteBuffer body) {
        ByteBuffer copy = body.asReadOnlyBuffer();
        byte[] bytes = new byte[copy.remaining()];
        copy.get(bytes);
        return bytes;
    }

    @PreDestroy
    void close() {
        if (consumer != null) {
            try {
                consumer.close();
            } catch (Exception ignored) {
                // Shutdown must continue closing the Data Plane.
            }
        }
    }
}
