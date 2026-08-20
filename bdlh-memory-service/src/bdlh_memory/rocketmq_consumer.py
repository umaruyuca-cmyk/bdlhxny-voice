from __future__ import annotations

import json
from typing import Any

from .domain import MemoryCandidate
from .service import MemoryApplication


class RocketMqMemoryConsumer:
    """RocketMQ 5.x gRPC PushConsumer; ACK occurs only after local Inbox processing succeeds."""

    TOPIC = "bdlh.memory.commands"
    GROUP = "bdlh-memory-consumer"

    def __init__(self, application: MemoryApplication, endpoints: str) -> None:
        self._application = application
        self._endpoints = endpoints
        self._consumer: Any | None = None

    def start(self) -> None:
        from rocketmq.v5.client import ClientConfiguration, Credentials
        from rocketmq.v5.consumer import ConsumeResult, MessageListener, PushConsumer
        from rocketmq.v5.model import FilterExpression

        application = self._application

        class Listener(MessageListener):
            def consume(self, message: Any) -> Any:
                try:
                    envelope = json.loads(bytes(message.body).decode("utf-8"))
                    payload = dict(envelope["payload"])
                    candidate = MemoryCandidate(
                        event_id=envelope["event_id"],
                        authenticated_user_id=envelope["authenticated_user_id"],
                        content=payload["content"],
                        metadata=payload["metadata"],
                    )
                    import asyncio
                    asyncio.run(application.consume(candidate))
                    return ConsumeResult.SUCCESS
                except Exception:
                    return ConsumeResult.FAILURE

        config = ClientConfiguration(self._endpoints, Credentials())
        self._consumer = PushConsumer(
            config, self.GROUP, Listener(), {self.TOPIC: FilterExpression("*")},
            consumption_thread_count=1,
        )
        self._consumer.start()

    def shutdown(self) -> None:
        if self._consumer is not None:
            self._consumer.shutdown()
