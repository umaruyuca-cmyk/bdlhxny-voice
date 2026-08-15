package com.bdlh.runtime.service;

import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 验证模型文本只有通过发送前护栏后才会进入SSE下游。
 */
class GuardedOutputServiceTest {

    private final GuardedOutputService service =
            new GuardedOutputService(new GuardrailService());

    @Test
    void shouldEmitSafeCompleteSentences() {
        List<String> result = service.guard(Flux.just(
                        "结论需要结合风险。",
                        "历史表现不代表未来收益"))
                .collectList()
                .block();

        assertThat(result).containsExactly(
                "结论需要结合风险。",
                "历史表现不代表未来收益");
    }

    @Test
    void shouldBlockForbiddenSentenceBeforeEmission() {
        List<String> emitted = new ArrayList<>();

        assertThatThrownBy(() -> service.guard(Flux.just(
                                "这个方案稳赚",
                                "。后续内容不应发送。"))
                        .doOnNext(emitted::add)
                        .collectList()
                        .block())
                .isInstanceOf(OutputGuardrailException.class);
        assertThat(emitted).isEmpty();
    }
}
