package com.bdlh.runtime.migration;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertTrue;

class TaskOutboxMigrationContractTest {

    @Test
    void migrationDefinesJavaOwnedOutboxAndLocalInbox() throws IOException {
        String migration = new String(
                getClass().getResourceAsStream("/db/migration/V3__task_outbox_and_consumer_inbox.sql").readAllBytes(),
                StandardCharsets.UTF_8);

        assertTrue(migration.contains("CREATE TABLE runtime.financial_task"));
        assertTrue(migration.contains("CREATE TABLE runtime.outbox_event"));
        assertTrue(migration.contains("CREATE TABLE runtime.consumer_inbox"));
        assertTrue(migration.contains("PRIMARY KEY (consumer_group, event_id)"));
        assertTrue(migration.contains("status IN ('PENDING', 'PUBLISHING', 'PUBLISHED', 'FAILED')"));
        assertTrue(migration.contains("compensation_required BOOLEAN NOT NULL DEFAULT FALSE"));
    }
}
