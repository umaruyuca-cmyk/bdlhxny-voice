package com.bdlh.runtime.dto;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 验证前端标的上下文只能使用固定代码和资产类型。
 */
class ChatInstrumentTest {

    @Test
    void shouldNormalizeSelectedInstrument() {
        ChatInstrument result = ChatInstrument.normalize(
                new ChatInstrument(" 600519 ", " STOCK "));

        assertThat(result.symbol()).isEqualTo("600519");
        assertThat(result.assetType()).isEqualTo("stock");
    }

    @Test
    void shouldRejectInvalidInstrument() {
        assertThatThrownBy(() -> ChatInstrument.normalize(
                new ChatInstrument("600519;rm", "stock")))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
