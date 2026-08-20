package com.bdlh.runtime.registry;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/** Read-only registry catalog projection for the Python orchestrator. */
@Service
public class RegistrySnapshotService {

    private static final Map<String, String> QUERIES = registryQueries();

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public RegistrySnapshotService(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public JsonNode snapshot() {
        var root = objectMapper.createObjectNode();
        QUERIES.forEach((key, query) -> root.set(key, readArray(query)));
        return root;
    }

    private JsonNode readArray(String query) {
        String json = jdbcTemplate.queryForObject(query, String.class);
        try {
            return objectMapper.readTree(json == null ? "[]" : json);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("registry catalog contains invalid JSON", exception);
        }
    }

    private static Map<String, String> registryQueries() {
        Map<String, String> queries = new LinkedHashMap<>();
        queries.put("operations", arrayQuery("bdlh_runtime_operation", "code"));
        queries.put("toolsets", arrayQuery("bdlh_runtime_toolset", "name"));
        queries.put("capabilities", arrayQuery("bdlh_runtime_capability", "name"));
        queries.put("capabilityOperations", arrayQuery("bdlh_runtime_capability_operation", "capability_name, operation_code"));
        queries.put("capabilityToolsets", arrayQuery("bdlh_runtime_capability_toolset", "capability_name, toolset_name"));
        queries.put("skills", arrayQuery("bdlh_runtime_skill", "skill_id"));
        queries.put("skillOperations", arrayQuery("bdlh_runtime_skill_operation", "skill_id, operation_code"));
        queries.put("skillCapabilities", arrayQuery("bdlh_runtime_skill_capability", "skill_id, capability_name"));
        queries.put("runtimeAllowlist", arrayQuery("bdlh_runtime_runtime_allowlist", "runtime_id, operation_code"));
        queries.put("entitlements", arrayQuery("bdlh_runtime_account_entitlement", "account_id, operation_code"));
        queries.put("fastpathRoutes", arrayQuery("bdlh_runtime_fastpath_route", "name"));
        queries.put("fastpathUtterances", arrayQuery("bdlh_runtime_fastpath_utterance", "id"));
        queries.put("budgets", arrayQuery("bdlh_runtime_run_budget", "profile"));
        queries.put("topicCapabilities", arrayQuery("bdlh_runtime_topic_capability", "topic, capability_name"));
        return Map.copyOf(queries);
    }

    private static String arrayQuery(String table, String orderBy) {
        return "SELECT COALESCE(jsonb_agg(to_jsonb(item)), '[]'::jsonb)::text FROM "
                + "(SELECT * FROM registry." + table + " ORDER BY " + orderBy + ") item";
    }
}
