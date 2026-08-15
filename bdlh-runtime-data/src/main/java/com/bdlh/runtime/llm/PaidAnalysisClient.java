package com.bdlh.runtime.llm;

import com.bdlh.runtime.agent.routing.PaidModelPermit;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;

/**
 * 作为业务层唯一可见的付费分析模型入口，拒绝未携带有效门禁许可的调用。
 */
@Component
public class PaidAnalysisClient {

    private final DeepSeekClient deepSeekClient;

    public PaidAnalysisClient(DeepSeekClient deepSeekClient) {
        this.deepSeekClient = deepSeekClient;
    }

    /**
     * 只在统一门禁明确放行后调用 DeepSeek，避免业务组件直接访问原始付费客户端。
     */
    public Flux<String> streamChat(PaidModelPermit permit, String systemPrompt, String userMessage) {
        if (permit == null || !permit.allowed()) {
            throw new IllegalStateException("缺少有效的付费模型许可");
        }
        // 1. 延迟创建真实模型流，确保上层可以在订阅前完成审计与模型门禁。
        return Flux.defer(() -> deepSeekClient.streamChat(systemPrompt, userMessage));
    }
}
