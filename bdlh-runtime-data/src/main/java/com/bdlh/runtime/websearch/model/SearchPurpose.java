package com.bdlh.runtime.websearch.model;

/**
 * 表示 BDLH Agent Runtime 允许发起的外部资料用途，避免模型构造任意搜索类型。
 */
public enum SearchPurpose {
    NEWS_CATALYST,
    COMPANY_ANNOUNCEMENT,
    POLICY_UPDATE,
    KNOWLEDGE_VERIFY,
    MARKET_ATTENTION
}
