package com.stockwise.tool;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证 Skill JSON 版本契约、行情时效与追高硬规则。
 */
class StockSkillContractValidatorTest {

    private final ObjectMapper mapper = new ObjectMapper();
    private final StockSkillContractValidator validator = new StockSkillContractValidator(mapper);

    @Test
    void shouldAnnotateBlockedDirectionalSignalAndHardChase() throws Exception {
        String json = """
                {
                  "schemaVersion":"1.1",
                  "command":"stock",
                  "timezone":"Asia/Shanghai",
                  "asOf":"2026-07-27 10:00:00",
                  "dataQuality":{"status":"delayed","label":"延时","allowsDirectionalSignal":false},
                  "methodology":{
                    "id":"stockwise-objective-analysis",
                    "version":"1.0.0",
                    "rules":[{"ruleId":"DATA-FRESH-001"}]
                  },
                  "decisionBasis":{"verdict":"wait"},
                  "data":{
                    "dataQuality":{"status":"delayed","label":"延时","allowsDirectionalSignal":false},
                    "chase":{"level":"hard"}
                  }
                }
                """;

        JsonNode result = mapper.readTree(validator.validateAndAnnotate(json, "stock"));

        assertTrue(result.path("consumerPolicy").path("observationValidated").asBoolean());
        assertFalse(result.path("consumerPolicy").path("directionalSignalAllowed").asBoolean());
        assertFalse(result.path("consumerPolicy").path("buyOrAddAllowed").asBoolean());
        assertTrue(result.path("consumerPolicy").path("hardChaseBlocked").asBoolean());
        assertTrue(result.path("consumerPolicy").path("reasons").size() >= 2);
    }

    @Test
    void shouldRejectUnsupportedSchemaVersion() {
        String json = """
                {"schemaVersion":"2.0","command":"stock","data":{}}
                """;

        assertThrows(IllegalArgumentException.class, () -> validator.validate(json, "stock"));
    }

    @Test
    void shouldRejectUnexpectedCommand() {
        String json = """
                {"schemaVersion":"1.1","command":"sector","data":{}}
                """;

        assertThrows(IllegalArgumentException.class, () -> validator.validate(json, "stock"));
    }

    @Test
    void shouldRejectOpaqueJsonWithoutFreshnessContract() {
        String json = """
                {
                  "schemaVersion":"1.1",
                  "command":"portfolio",
                  "timezone":"Asia/Shanghai",
                  "data":{}
                }
                """;

        assertThrows(IllegalArgumentException.class, () -> validator.validate(json, "portfolio"));
    }

    @Test
    void shouldRejectContractWithoutMethodologyTrace() {
        String json = """
                {
                  "schemaVersion":"1.1",
                  "command":"sector",
                  "timezone":"Asia/Shanghai",
                  "asOf":"2026-07-29 10:00:00",
                  "dataQuality":{"status":"realtime","allowsDirectionalSignal":true},
                  "decisionBasis":{"verdict":"observe"},
                  "data":{}
                }
                """;

        assertThrows(IllegalArgumentException.class, () -> validator.validate(json, "sector"));
    }
}
