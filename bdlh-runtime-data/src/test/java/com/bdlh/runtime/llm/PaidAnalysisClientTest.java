package com.bdlh.runtime.llm;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

/**
 * 验证业务可见的付费模型入口无法在缺少门禁许可时调用原始客户端。
 */
class PaidAnalysisClientTest {

    @Test
    void missingPermitCannotReachDeepSeek() {
        DeepSeekClient deepSeekClient = mock(DeepSeekClient.class);
        PaidAnalysisClient client = new PaidAnalysisClient(deepSeekClient);

        assertThatThrownBy(() -> client.streamChat(null, "system", "question"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("付费模型许可");
        verifyNoInteractions(deepSeekClient);
    }
}
