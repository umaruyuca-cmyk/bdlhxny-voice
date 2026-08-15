package com.bdlh.runtime.llm;

/**
 * 问题分类意图，Step 2 由 Ollama 轻量模型判定，决定后续加载哪个 Skill。
 */
public enum ChatIntent {

    INVESTMENT_QA,      // 投资知识问答
    PORTFOLIO_ANALYSIS, // 持仓组合分析
    STOCK_ANALYSIS,     // 单标的深度分析
    GENERAL_CHAT        // 通用闲聊兜底
}
