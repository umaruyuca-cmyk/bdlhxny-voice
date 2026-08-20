# BDLH Memory Service

This is the standalone Python service for L3 semantic memory only. It does not
own chat history, run registry data, task data, or L4 user profiles.

## Data and event ownership

The Java Data Plane accepts a memory candidate and records it in its
transactional outbox. Its `bdlh.memory.commands` RocketMQ event is consumed by
this service as consumer group `bdlh-memory-consumer`. Deduplication is local
to `memory.consumer_inbox`; this service never writes `runtime.consumer_inbox`.

Run the service migration once with the `bdlh_memory_service` database role:

```powershell
$env:MEMORY_POSTGRES_DSN = 'postgresql://bdlh_memory_service:password@postgres:5432/bdlh'
python scripts/migrate.py
```

## Required production configuration

`MEM0_CONFIG_JSON` is required in production. It must configure Mem0's
pgvector vector store to use the dedicated `memory` schema and the
`bdlh_memory_service` role. The JSON remains provider-specific intentionally,
because Mem0's provider configuration changes independently of this service.

All internal HTTP calls require both `X-Internal-Token` and
`X-Authenticated-User-Id`. The service rejects a request when its payload or
path user ID differs from the authenticated user scope.

If recall fails, the orchestrator treats it as an empty result. Candidate
ingestion is asynchronous and never blocks answer generation.
