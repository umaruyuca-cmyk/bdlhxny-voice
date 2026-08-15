package com.bdlh.runtime.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 集中创建有界业务线程池，避免SSE和工具调用在高并发下无限创建线程。
 */
@Configuration
public class AsyncExecutorConfig {

    /**
     * 创建Agent流程线程池，队列满时由入口返回SYSTEM_BUSY。
     */
    @Bean(name = "agentFlowExecutor", destroyMethod = "shutdown")
    public ExecutorService agentFlowExecutor(
            @Value("${bdlh_runtime.execution.agent.core-threads:4}") int coreThreads,
            @Value("${bdlh_runtime.execution.agent.max-threads:16}") int maxThreads,
            @Value("${bdlh_runtime.execution.agent.queue-capacity:100}") int queueCapacity) {
        return boundedExecutor(
                coreThreads, maxThreads, queueCapacity, "bdlh_runtime-agent-");
    }

    /**
     * 创建ReAct工具线程池，隔离外部工具阻塞与主对话流程。
     */
    @Bean(name = "reactToolExecutor", destroyMethod = "shutdown")
    public ExecutorService reactToolExecutor(
            @Value("${bdlh_runtime.execution.react-tool.core-threads:4}") int coreThreads,
            @Value("${bdlh_runtime.execution.react-tool.max-threads:8}") int maxThreads,
            @Value("${bdlh_runtime.execution.react-tool.queue-capacity:64}") int queueCapacity) {
        return boundedExecutor(
                coreThreads, maxThreads, queueCapacity, "bdlh_runtime-react-tool-");
    }

    /**
     * 创建语义路由分类线程池，隔离前置模型超时与最终分析资源。
     */
    @Bean(name = "routingClassifierExecutor", destroyMethod = "shutdown")
    public ExecutorService routingClassifierExecutor(
            @Value("${bdlh_runtime.routing.semantic.max-concurrent-calls:8}") int maxConcurrentCalls) {
        int concurrency = Math.max(1, maxConcurrentCalls);
        return boundedExecutor(
                concurrency, concurrency, concurrency, "bdlh_runtime-routing-");
    }

    private ExecutorService boundedExecutor(int coreThreads,
                                            int maxThreads,
                                            int queueCapacity,
                                            String threadPrefix) {
        int safeCore = Math.max(1, coreThreads);
        int safeMax = Math.max(safeCore, maxThreads);
        int safeQueue = Math.max(1, queueCapacity);
        return new ThreadPoolExecutor(
                safeCore,
                safeMax,
                60L,
                TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(safeQueue),
                namedThreadFactory(threadPrefix),
                new ThreadPoolExecutor.AbortPolicy());
    }

    private ThreadFactory namedThreadFactory(String prefix) {
        AtomicInteger sequence = new AtomicInteger();
        return runnable -> {
            Thread thread = new Thread(runnable, prefix + sequence.incrementAndGet());
            thread.setDaemon(true);
            return thread;
        };
    }
}
