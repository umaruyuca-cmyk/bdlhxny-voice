package com.bdlh.runtime.migration;

import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class RuntimePersistenceMigrationContractTest {

    @Test
    void m0PersistenceMigrationOnlyCreatesRuntimeOwnedTables() throws Exception {
        var resource = new ClassPathResource("db/migration/V2__runtime_m0_persistence_tables.sql");
        String sql = new String(resource.getInputStream().readAllBytes(), StandardCharsets.UTF_8);

        assertThat(sql).contains("runtime.chat_session");
        assertThat(sql).contains("runtime.chat_message");
        assertThat(sql).contains("runtime.run_registry");
        assertThat(sql).contains("runtime.analysis_history");
        assertThat(sql).doesNotContainPattern("(?i)\\b(checkpoint|memory|public)\\.[a-z_]");
    }
}
