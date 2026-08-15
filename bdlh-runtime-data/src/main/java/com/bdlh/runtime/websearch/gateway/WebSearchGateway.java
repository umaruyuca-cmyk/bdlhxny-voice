package com.bdlh.runtime.websearch.gateway;

import com.bdlh.runtime.websearch.model.SearchTask;
import com.bdlh.runtime.websearch.model.WebSearchResponse;

import java.util.List;

/**
 * 隔离 Agent 业务与共享搜索服务的传输协议，便于替换部署地址和实现。
 */
public interface WebSearchGateway {

    /**
     * 执行已经规划和校验的结构化搜索任务。
     */
    WebSearchResponse search(List<SearchTask> tasks);
}
