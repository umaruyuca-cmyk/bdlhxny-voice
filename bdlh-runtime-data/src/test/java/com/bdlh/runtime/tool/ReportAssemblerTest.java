package com.bdlh.runtime.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.bdlh.runtime.dto.AnalysisReport;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 验证固定报告链执行与 Agent 工具链一致的时效和空值硬规则。
 */
class ReportAssemblerTest {

    private final ObjectMapper mapper = new ObjectMapper();
    private final StockSkillContractValidator validator = new StockSkillContractValidator(mapper);
    private final ReportAssembler assembler = new ReportAssembler(mapper, validator);

    @Test
    void shouldForceWaitWhenDirectionalSignalIsNotAllowed() {
        AnalysisReport report = assembler.assemble(stockJson(false, "none"));

        assertEquals("观望", report.decision().action());
        assertEquals("2026-07-27 10:00:00", report.asOf());
        assertTrue(report.levels().risk().compareTo(new BigDecimal("9.70")) == 0);
        assertNull(report.levels().confirm());
    }

    @Test
    void shouldBlockBuyWhenHardChaseIsActive() {
        AnalysisReport report = assembler.assemble(stockJson(true, "hard"));

        assertEquals("观望", report.decision().action());
    }

    private String stockJson(boolean allowsDirectionalSignal, String chaseLevel) {
        return """
                {
                  "schemaVersion":"1.1",
                  "command":"stock",
                  "timezone":"Asia/Shanghai",
                  "asOf":"2026-07-27 10:00:00",
                  "dataQuality":{
                    "status":"delayed",
                    "label":"延时",
                    "allowsDirectionalSignal":%s
                  },
                  "methodology":{
                    "id":"bdlh_runtime-objective-analysis",
                    "version":"1.0.0",
                    "rules":[{"ruleId":"DATA-FRESH-001"}]
                  },
                  "decisionBasis":{"verdict":"hold"},
                  "data":{
                    "code":"588200",
                    "name":"测试ETF",
                    "quote":{"price":10.2,"changeAmount":0.1,"changePct":0.99},
                    "score":{"signal":"buy","total":66},
                    "chase":{"level":"%s","label":"测试"},
                    "dataQuality":{
                      "status":"delayed",
                      "label":"延时",
                      "allowsDirectionalSignal":%s
                    },
                    "history":[{"close":10.1},{"close":10.2}],
                    "technical":{
                      "ma":{"ma5":10.1,"ma20":9.9,"ma60":10.0},
                      "support":{},
                      "alignment":"bullish",
                      "macd":{"state":"golden_cross"},
                      "rsi":{"rsi6":60.0,"zone":"healthy"},
                      "volume":{"volumeRatio":1.1},
                      "deviation":{"ma20":3.03}
                    }
                  }
                }
                """.formatted(allowsDirectionalSignal, chaseLevel, allowsDirectionalSignal);
    }
}
