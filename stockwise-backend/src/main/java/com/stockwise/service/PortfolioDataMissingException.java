package com.stockwise.service;

/**
 * 表示用户尚未配置组合分析必需的持仓或资金事实，应追问而不是使用示例数据。
 */
public class PortfolioDataMissingException extends RuntimeException {

    public PortfolioDataMissingException(String message) {
        super(message);
    }
}
