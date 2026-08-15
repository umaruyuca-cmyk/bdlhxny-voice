package com.bdlh.runtime.service;

import com.bdlh.runtime.dto.GuardrailResult;
import org.springframework.stereotype.Service;
import reactor.core.Disposable;
import reactor.core.publisher.Flux;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 在模型片段发送到浏览器之前按完整句子执行输出护栏，阻止违规内容泄漏。
 */
@Service
public class GuardedOutputService {

    private static final int MAX_PENDING_CHARS = 512;

    private final GuardrailService guardrailService;

    public GuardedOutputService(GuardrailService guardrailService) {
        this.guardrailService = guardrailService;
    }

    /**
     * 缓冲未完成句子并输出已经校验的安全片段。
     */
    public Flux<String> guard(Flux<String> source) {
        return Flux.create(sink -> {
            Object lock = new Object();
            StringBuilder pending = new StringBuilder();
            StringBuilder validated = new StringBuilder();
            AtomicBoolean terminated = new AtomicBoolean();
            AtomicReference<Disposable> subscription = new AtomicReference<>();

            Disposable disposable = source.subscribe(token -> {
                synchronized (lock) {
                    if (terminated.get() || token == null || token.isEmpty()) {
                        return;
                    }
                    // 1. 只在出现完整句子边界后检查并向下游发送
                    pending.append(token);
                    int boundary = flushBoundary(pending);
                    if (boundary < 0) {
                        return;
                    }
                    String segment = pending.substring(0, boundary + 1);
                    pending.delete(0, boundary + 1);
                    emitValidated(sink, validated, segment, terminated);
                }
            }, error -> {
                if (terminated.compareAndSet(false, true)) {
                    sink.error(error);
                }
            }, () -> {
                synchronized (lock) {
                    if (terminated.get()) {
                        return;
                    }
                    // 2. 流结束时校验没有标点的最后一个片段
                    String remainder = pending.toString();
                    pending.setLength(0);
                    if (!remainder.isEmpty()) {
                        emitValidated(sink, validated, remainder, terminated);
                    }
                    if (terminated.compareAndSet(false, true)) {
                        sink.complete();
                    }
                }
            });
            subscription.set(disposable);
            sink.onDispose(() -> {
                Disposable active = subscription.get();
                if (active != null && !active.isDisposed()) {
                    active.dispose();
                }
            });
        });
    }

    private void emitValidated(reactor.core.publisher.FluxSink<String> sink,
                               StringBuilder validated,
                               String segment,
                               AtomicBoolean terminated) {
        String candidate = validated + segment;
        GuardrailResult result = guardrailService.checkOutput(candidate);
        if (!result.passed()) {
            if (terminated.compareAndSet(false, true)) {
                sink.error(new OutputGuardrailException(result.reason()));
            }
            return;
        }
        validated.append(segment);
        sink.next(segment);
    }

    private int flushBoundary(CharSequence text) {
        for (int index = text.length() - 1; index >= 0; index--) {
            char value = text.charAt(index);
            if (value == '。' || value == '！' || value == '？'
                    || value == '!' || value == '?' || value == '\n') {
                return index;
            }
        }
        // 1. 极长无标点文本按固定上限切片，仍使用累计全文执行护栏
        return text.length() >= MAX_PENDING_CHARS ? MAX_PENDING_CHARS - 1 : -1;
    }
}
