package com.stockwise.dto;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 验证双模式值解析和服务端会话隔离保持稳定。
 */
class ChatModeTest {

    @Test
    void shouldIsolateGeneralAndStockSessionsForSameClientSession() {
        String general = ChatMode.GENERAL.scopedSessionId("session_1234");
        String stock = ChatMode.STOCK_AGENT.scopedSessionId("session_1234");

        assertThat(general).startsWith("general_");
        assertThat(stock).startsWith("stock_");
        assertThat(general).isNotEqualTo(stock);
        assertThat(ChatMode.GENERAL.scopedSessionId("session_1234")).isEqualTo(general);
    }

    @Test
    void shouldAcceptStableFrontendModeValues() {
        assertThat(ChatMode.from("general")).isEqualTo(ChatMode.GENERAL);
        assertThat(ChatMode.from("stock")).isEqualTo(ChatMode.STOCK_AGENT);
    }
}
