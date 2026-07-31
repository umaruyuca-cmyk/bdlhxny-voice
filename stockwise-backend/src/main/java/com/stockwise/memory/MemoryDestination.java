package com.stockwise.memory;

/**
 * 表示不同业务事实必须进入的确定性存储区域。
 */
public enum MemoryDestination {
    WORKING_REDIS,
    EPISODIC_POSTGRES,
    SEMANTIC_PGVECTOR,
    BUSINESS_POSTGRES
}
