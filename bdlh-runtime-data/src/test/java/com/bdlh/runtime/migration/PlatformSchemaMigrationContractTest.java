package com.bdlh.runtime.migration;

import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class PlatformSchemaMigrationContractTest {

    @Test
    void flywayBaselineOnlyTouchesJavaOwnedSchemas() throws Exception {
        var resource = new ClassPathResource("db/migration/V1__platform_schema_contract.sql");
        String sql = new String(resource.getInputStream().readAllBytes(), StandardCharsets.UTF_8);

        assertThat(sql).contains("registry.platform_schema_contract");
        assertThat(sql).contains("'business', 'v1', 'bdlh-runtime-data'");
        assertThat(sql).contains("'runtime', 'v1', 'bdlh-runtime-data'");
        assertThat(sql).contains("'registry', 'v1', 'bdlh-runtime-data'");
        assertThat(sql).doesNotContainPattern("(?i)\\b(checkpoint|memory|public)\\.[a-z_]");
    }
}
